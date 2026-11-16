#!/usr/bin/env node
/**
 * i7_autoplay LLM コパイロット（pi-durable 版）。
 *
 * `assets/prompts/supervisor_loop.md`（Claude Code /loop 用プロンプト）を
 * pi-durable の durable task として実装したもの。会話・タスク状態は SQLite に
 * コミットされるため、プロセスが落ちても `watch` を再起動すれば途中から再開する。
 *
 * 使い方:
 *   node src/supervisor.mjs watch --target <epoch> [--interval 600] [--model anthropic/claude-sonnet-4-6]
 *   node src/supervisor.mjs once  [--model ...]           # 1サイクルだけ実行して終了（動作確認用）
 *   node src/supervisor.mjs watch --faux                  # APIキー不要のオフライン疎通（テスト用）
 *
 * 環境変数: ANTHROPIC_API_KEY（実モデル使用時）。I7_COPILOT_* は CLI 引数の既定値。
 */
import { execFile } from "node:child_process";
import { appendFileSync, existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels } from "@earendil-works/pi-ai";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { fauxProvider, fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import { obj, str, int, opt } from "@earendil-works/pi-schema";
import {
  defineDoc,
  defineExtension,
  defineTask,
  defineTool,
  Harness,
  createRegistry,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";

const execFileAsync = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const COPILOT_DIR = resolve(HERE, "..");
const REPO_ROOT = resolve(COPILOT_DIR, "../..");
const PROMPT_PATH = join(REPO_ROOT, "assets/prompts/pi_durable_copilot.md");
const AUTORUN_LOG = "/tmp/i7_autorun.log";
const SUPERVISOR_LOG = "/tmp/i7_supervisor.log";
const DBG_DIR = "/tmp/i7dbg";
const JSONL_LOG = join(COPILOT_DIR, "data/copilot.log.jsonl");
const DB_PATH = join(COPILOT_DIR, "data/copilot.sqlite");

const context = BACKGROUND_CONTEXT;

// ---------------------------------------------------------------------------
// CLI 引数
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) args[key] = true;
      else { args[key] = next; i++; }
    } else args._.push(a);
  }
  return args;
}

const USAGE = `usage:
  node src/supervisor.mjs watch --target <epoch> [--interval 600] [--model provider/modelId] [--db path] [--faux]
  node src/supervisor.mjs once  [--model provider/modelId] [--db path] [--faux]

既定値: interval=${process.env.I7_COPILOT_INTERVAL ?? 600}s, model=${process.env.I7_COPILOT_MODEL ?? "anthropic/claude-sonnet-4-6"}, db=${DB_PATH}
`;

// ---------------------------------------------------------------------------
// タスクが使う小さな道具（シェル実行・ログ読み・スクショ・制御フラグ）
// ---------------------------------------------------------------------------
async function sh(cmd, args, { timeoutMs = 15_000 } = {}) {
  try {
    const { stdout, stderr } = await execFileAsync(cmd, args, {
      timeout: timeoutMs,
      maxBuffer: 4 * 1024 * 1024,
      cwd: REPO_ROOT,
    });
    return { ok: true, stdout: String(stdout), stderr: String(stderr) };
  } catch (e) {
    return { ok: false, stdout: String(e.stdout ?? ""), stderr: String(e.stderr ?? e.message ?? e), code: e.code };
  }
}

async function shText(command, { timeoutMs = 60_000 } = {}) {
  // run_command 用: シェル解釈が必要なため /bin/sh -c。
  try {
    const { stdout, stderr } = await execFileAsync("/bin/sh", ["-c", command], {
      timeout: timeoutMs,
      maxBuffer: 4 * 1024 * 1024,
      cwd: REPO_ROOT,
    });
    return { ok: true, stdout: String(stdout), stderr: String(stderr) };
  } catch (e) {
    return { ok: false, stdout: String(e.stdout ?? ""), stderr: String(e.stderr ?? e.message ?? e), code: e.code };
  }
}

function tailLines(path, n) {
  try {
    const lines = readFileSync(path, "utf8").split("\n");
    return lines.slice(-n).join("\n");
  } catch {
    return `(cannot read ${path})`;
  }
}

function newestShot() {
  try {
    const files = readdirSync(DBG_DIR)
      .filter((f) => f.endsWith(".png"))
      .map((f) => ({ f, m: statSync(join(DBG_DIR, f)).mtimeMs }))
      .sort((a, b) => b.m - a.m);
    return files[0] ? join(DBG_DIR, files[0].f) : undefined;
  } catch {
    return undefined;
  }
}

function clearCount(text) {
  let max = 0;
  const re = /ライブ クリア（通算 (\d+)）/g;
  let m;
  while ((m = re.exec(text)) !== null) max = Math.max(max, Number(m[1]));
  return max;
}

/** 会話スコープの制御ドキュメント: end_session / write_report が書き、cycle フェーズが読む。
 *  ツール内の api.taskId はツール呼び出し自身のタスク ID なので、会話 ID でキーする。 */
const SupervisorControl = defineDoc({
  kind: "i7.supervisor-control",
  version: 1,
  scope: "conversation",
  history: "latest",
  fork: "initial",
  initial: () => ({ done: false, reason: "", lastReport: "" }),
  checkpointWhen: () => false,
});

// run_command の許可リスト: 読み取り専用のものだけ。破壊的操作・プロセス kill・
// 書き込みは専用ツール（open_mirroring / restart_supervisor）か人間判断に限定する。
const ALLOWED_COMMAND = new RegExp(
  "^(" +
    [
      "pgrep\\b.*",
      "ps\\b.*",
      "tail\\b.*",
      "head\\b.*",
      "grep\\b.*",
      "wc\\b.*",
      "cat\\b.*",
      "ls\\b.*",
      "date\\b.*",
      "df\\b.*",
      "sips\\b.*",
      "python3?\\s+tools/driver\\.py\\s+info",
      "python3?\\s+tools/driver\\.py\\s+shot\\b.*", // shot は /tmp/i7dbg への書き込みのみ許可
      "sleep\\s+\\d+",
    ].join("|") +
    ")$",
);

const CopilotTools = defineExtension({
  name: "i7-copilot-tools",
  tools: [
    defineTool({
      name: "check_status",
      description:
        "周回システムの一括状態確認。autolive/supervise プロセスの生存、ミラーリングウィンドウ、" +
        "/tmp/i7_autorun.log 末尾40行、通算クリア数、警告痕跡を返す。毎サイクル最初に呼ぶこと。",
      parameters: obj({}),
      replay: "safe",
      async execute(_args, _api, _ctx) {
        const [pgrepAuto, pgrepSup, driverInfo] = await Promise.all([
          sh("pgrep", ["-fl", "autolive\\.py"]),
          sh("pgrep", ["-fl", "supervise_autolive"]),
          sh("python3", ["tools/driver.py", "info"], { timeoutMs: 10_000 }),
        ]);
        const autorun = tailLines(AUTORUN_LOG, 40);
        const supervisor = tailLines(SUPERVISOR_LOG, 15);
        const warns = (autorun.match(/\[(warn|error|停止|停止理由)/g) ?? []).slice(-8);
        const report = [
          "## processes",
          `autolive.py: ${pgrepAuto.ok && pgrepAuto.stdout.trim() ? pgrepAuto.stdout.trim() : "(not running)"}`,
          `supervise_autolive: ${pgrepSup.ok && pgrepSup.stdout.trim() ? pgrepSup.stdout.trim() : "(not running)"}`,
          "## driver.py info",
          driverInfo.ok ? driverInfo.stdout.trim() || "(no output)" : `(failed: ${driverInfo.stderr.trim()})`,
          `## /tmp/i7_autorun.log (last 40 lines, clears=${clearCount(autorun)})`,
          autorun,
          `## /tmp/i7_supervisor.log (last 15 lines)`,
          supervisor,
          `## recent warnings`,
          warns.length ? warns.join("\n") : "(none)",
        ].join("\n");
        return { output: [{ type: "text", text: report }] };
      },
    }),

    defineTool({
      name: "read_log",
      description:
        "ログファイルを読む。path は /tmp/i7_autorun.log か /tmp/i7_supervisor.log。" +
        "grep を指定すると一致行と前後 context 行、なければ末尾 lines 行を返す。",
      parameters: obj({
        path: str({ description: "ログファイルのパス" }),
        grep: opt(str({ description: "grep パターン（ERE）" })),
        context_lines: opt(int({ description: "grep の前後行数", default: 3 })),
        lines: opt(int({ description: "末尾から読む行数", default: 80 })),
      }),
      replay: "safe",
      async execute(args, _api, _ctx) {
        const path = args.path;
        if (![AUTORUN_LOG, SUPERVISOR_LOG].includes(path)) {
          return { output: [{ type: "text", text: `read_log: 許可されたのは ${AUTORUN_LOG} と ${SUPERVISOR_LOG} のみ` }], isError: true };
        }
        if (!existsSync(path)) return { output: [{ type: "text", text: `(no such file: ${path})` }] };
        if (args.grep) {
          const n = args.context_lines ?? 3;
          const r = await sh("grep", ["-nE", "-C", String(n), args.grep, path], { timeoutMs: 10_000 });
          const text = (r.stdout || r.stderr || "(no match)").slice(-8000);
          return { output: [{ type: "text", text }] };
        }
        const n = Math.min(args.lines ?? 80, 400);
        return { output: [{ type: "text", text: tailLines(path, n) }] };
      },
    }),

    defineTool({
      name: "run_command",
      description:
        "読み取り専用コマンドを実行する（pgrep/ps/tail/head/grep/wc/cat/ls/date/df/sips/" +
        "python3 tools/driver.py info|shot/sleep のみ許可）。副作用のある操作は拒否される。" +
        "60秒でタイムアウト。",
      parameters: obj({ command: str({ description: "実行するシェルコマンド" }) }),
      replay: "safe",
      async execute(args, _api, _ctx) {
        if (!ALLOWED_COMMAND.test(args.command.trim())) {
          return {
            output: [{ type: "text", text: `run_command: 許可リスト外です: ${args.command}\n許可: pgrep ps tail head grep wc cat ls date df sips "python3 tools/driver.py info|shot" sleep` }],
            isError: true,
          };
        }
        const r = await shText(args.command, { timeoutMs: 60_000 });
        const out = [r.stdout, r.stderr ? `--- stderr ---\n${r.stderr}` : ""].filter(Boolean).join("\n").slice(-8000);
        return { output: [{ type: "text", text: out || "(no output)" }], isError: !r.ok && r.code !== 1 };
      },
    }),

    defineTool({
      name: "look_at_shot",
      description:
        "スクリーンショット画像をあなたに見せる。path 省略時は /tmp/i7dbg/ の最新 PNG。" +
        "画像は次のユーザ入力として届くので、見えた内容を踏まえて次の判断をすること。" +
        "（画像非対応モデルでは内容は得られない。その場合は諦めて人間に通知する）",
      parameters: obj({ path: opt(str({ description: "/tmp/i7dbg/ 以下の PNG パス" })) }),
      replay: "safe",
      async execute(args, api, _ctx) {
        let path = args.path;
        if (!path) path = newestShot();
        if (!path) return { output: [{ type: "text", text: "look_at_shot: /tmp/i7dbg/ に PNG がありません" }] };
        const abs = path.startsWith("/") ? path : join(DBG_DIR, path);
        if (!existsSync(abs)) return { output: [{ type: "text", text: `look_at_shot: no such file: ${abs}` }], isError: true };
        const b64 = readFileSync(abs).toString("base64");
        // 会話に画像つき入力を1件追加する。requestId で重複を防ぐ。
        const handle = await api.conversation(api.conversationId, context);
        if (!handle) return { output: [{ type: "text", text: "look_at_shot: conversation handle unavailable" }], isError: true };
        await handle.submit(
          {
            type: "input",
            requestId: `look-${api.taskId}-${api.callId}`,
            content: [
              { type: "text", text: `スクリーンショットを確認してください: ${abs}` },
              { type: "image", data: b64, mimeType: "image/png" },
            ],
            whenBusy: "followUp",
          },
          context,
        );
        return {
          output: [{ type: "text", text: `look_at_shot: ${abs} を会話に送りました。画像が見えたら内容を報告し、見えなければその旨を報告してください。` }],
        };
      },
    }),

    defineTool({
      name: "open_mirroring",
      description: "iPhone ミラーリングを再接続する（open -b com.apple.ScreenContinuity）。切断検知時のみ使用。",
      parameters: obj({}),
      async execute(_args, _api, _ctx) {
        const r = await sh("open", ["-b", "com.apple.ScreenContinuity"]);
        return {
          output: [{ type: "text", text: r.ok ? "open_mirroring: ScreenContinuity を起動しました。30秒後に check_status で確認してください。" : `open_mirroring failed: ${r.stderr}` }],
          isError: !r.ok,
        };
      },
    }),

    defineTool({
      name: "restart_supervisor",
      description:
        "supervise_autolive.sh を nohup で再始動する。autolive と supervisor が両方死んでいるときだけ使用。" +
        "target_epoch はタスク入力の値（省略時は現在+2時間）。",
      parameters: obj({ target_epoch: opt(int({ description: "終了 UNIX 時刻（秒）" })) }),
      async execute(args, _api, _ctx) {
        const epoch = args.target_epoch ?? Math.floor(Date.now() / 1000) + 7200;
        const cmd = `nohup tools/ops/supervise_autolive.sh ${epoch} >> /tmp/i7_supervisor.log 2>&1 &`;
        const r = await shText(cmd);
        return {
          output: [{ type: "text", text: r.ok ? `restart_supervisor: target=${epoch} で起動しました` : `restart_supervisor failed: ${r.stderr}` }],
          isError: !r.ok,
        };
      },
    }),

    defineTool({
      name: "write_report",
      description: "サイクル報告をタスクの記録に保存する（任意）。最終行のテキスト報告と併用可。",
      parameters: obj({ text: str({ description: "報告テキスト" }) }),
      replay: "safe",
      async execute(args, api, ctx) {
        await api.commit(async (tx) => {
          const doc = await tx.doc(SupervisorControl, api.conversationId);
          doc.lastReport = args.text;
        }, ctx);
        return { output: [{ type: "text", text: "write_report: 保存しました" }] };
      },
    }),

    defineTool({
      name: "end_session",
      description:
        "監視セッションを終了する。目標時刻到達・人間待ちで自動復旧不能・人間が意図的に停止した場合のみ。" +
        "呼ぶ前に必ず最終報告テキストを書くこと。",
      parameters: obj({ reason: str({ description: "終了理由（人間向け1行）" }) }),
      async execute(args, api, ctx) {
        await api.commit(async (tx) => {
          const doc = await tx.doc(SupervisorControl, api.conversationId);
          doc.done = true;
          doc.reason = args.reason;
        }, ctx);
        return { output: [{ type: "text", text: `end_session: 監視を終了します（${args.reason}）。この後の報告が最終報告です。` }] };
      },
    }),
  ],
});

// ---------------------------------------------------------------------------
// durable task: wait(スリープ) → cycle(モデル1回) → sleep ... のループ
// ---------------------------------------------------------------------------
const SupervisorTask = defineTask(
  {
    name: "i7.supervise",
    version: 1,
    initial: () => ({ phase: "wait" }),
    phases: {
      wait: async (task, runtime, ctx) => {
        const until = runtime.now() + (task.input.firstDelayMs ?? 5000);
        await runtime.sleepUntil(until, { phase: "cycle", cycle: 0 }, ctx);
      },
      cycle: async (task, runtime, ctx) => {
        const cycle = task.state.checkpoint.cycle ?? 0;
        const requestId = `cycle-${task.input.attempt}-${cycle}`;

        // 1) 会話に今サイクルの指示を submit し、回答を待つ
        const conv = await runtime.conversation(runtime.conversationId, ctx);
        if (!conv) throw new Error("supervisor: own conversation handle unavailable");
        const submission = await conv.submit(
          {
            type: "input",
            requestId,
            content: `監視サイクル #${cycle + 1}。check_status から始めて、判断表に従って必要なら介入し、最後に1行の状態報告を書いてください。終了条件を満たす場合のみ end_session を呼んでください。`,
          },
          ctx,
        );
        const settled = await submission.wait(ctx);

        // 2) 回答テキストを transcript から取り出す
        let reportText = "";
        if (settled.status === "done" && settled.answer !== undefined) {
          const entry = await runtime.entry(settled.answer, ctx);
          const msgs = entry?.model ?? [];
          const texts = [];
          for (const m of msgs) {
            if (m.role === "assistant" && Array.isArray(m.content)) {
              for (const c of m.content) if (c.type === "text") texts.push(c.text);
            }
          }
          reportText = texts.join("\n").trim();
        }
        const interrupted = settled.status !== "done";

        // 3) 終了判定: end_session フラグ or 目標時刻超過
        const control = await runtime.snapshot(SupervisorControl, runtime.conversationId, ctx);
        const nowSec = Math.floor(runtime.now() / 1000);
        const expired = nowSec >= task.input.targetEpoch;
        const shouldEnd = Boolean(control?.done) || expired;

        const record = {
          ts: new Date(runtime.now()).toISOString(),
          cycle: cycle + 1,
          status: settled.status,
          reason: settled.status === "unanswered" ? settled.reason : undefined,
          report: reportText,
          end: shouldEnd,
          interrupted,
        };
        appendFileSync(JSONL_LOG, JSON.stringify(record) + "\n");
        console.log(`[copilot] cycle ${cycle + 1}: ${reportText || `(no answer: ${settled.status})`}`);

        // 4) 次のコミット: 終了 or 次サイクルへスリープ
        if (shouldEnd) {
          const reason = control?.reason || (expired ? "target_epoch reached" : "end_session");
          await runtime.commit(
            () => ({
              status: "terminal",
              outcome: { status: "completed", result: { cycles: cycle + 1, reason, lastReport: reportText } },
            }),
            ctx,
          );
          return;
        }
        const nextCycle = cycle + 1;
        const nextAt = runtime.now() + task.input.intervalSec * 1000;
        await runtime.commit(
          () => ({ status: "sleeping", until: nextAt, checkpoint: { phase: "cycle", cycle: nextCycle } }),
          ctx,
        );
      },
    },
    abort: async (task, runtime, ctx) => {
      await runtime.commit(
        () => ({ status: "terminal", outcome: { status: "aborted", error: { message: "supervisor aborted" } } }),
        ctx,
      );
    },
  },
  undefined,
);

const SupervisorExt = defineExtension({ name: "i7-supervisor", tasks: [SupervisorTask] });

// ---------------------------------------------------------------------------
// モデル / プロバイダ
// ---------------------------------------------------------------------------
function buildModels({ faux }) {
  const models = createModels();
  if (faux) {
    const f = fauxProvider({ provider: "faux", api: "faux", models: [{ id: "faux-1", name: "Faux", input: ["text", "image"] }] });
    models.setProvider(f.provider);
    const cycle = (_ctx, _opts, state) => {
      f.appendResponses([cycle]); // キューを自分で補充（無限供給）
      const n = state.callCount;
      if (n % 2 === 1) {
        // ツール呼び出し回。9回目以降は end_session で自壊（watch --faux のスモーク用）。
        const calls =
          n >= 9
            ? [fauxToolCall("end_session", { reason: "faux smoke: 疑似終了" })]
            : [fauxToolCall("check_status", {}), fauxToolCall("write_report", { text: `faux cycle ${Math.ceil(n / 2)}` })];
        return fauxAssistantMessage(calls, { stopReason: "toolUse" });
      }
      return fauxAssistantMessage(`faux report #${Math.ceil(n / 2)}: 正常に周回中（疎通確認）`);
    };
    f.setResponses([cycle]);
    return { models, faux: f };
  }
  models.setProvider(anthropicProvider());
  return { models };
}

function splitModelRef(ref) {
  const i = ref.indexOf("/");
  if (i <= 0) throw new Error(`--model は provider/modelId 形式で指定: ${ref}`);
  return { provider: ref.slice(0, i), modelId: ref.slice(i + 1) };
}

// ---------------------------------------------------------------------------
// ハーネス構築
// ---------------------------------------------------------------------------
async function openHarness({ dbPath, faux }) {
  const storage = await openNodeSqliteStorage(dbPath);
  const registry = createRegistry();
  registry.install(CopilotTools);
  registry.install(SupervisorExt);
  const { models } = buildModels({ faux });
  const harness = await Harness.open(
    storage,
    {
      models,
      registry,
      identity: { attribution: { name: "i7-autoplay-copilot", url: "https://github.com/yo4raw/i7_autoplay" } },
      settings: {
        compaction: { enabled: true, reserveTokens: 16384, keepRecentTokens: 20000 },
        retry: { maxRetries: 3 },
      },
      onReport: (report) => {
        console.error(`[copilot][report] ${report.kind}: ${report.error?.message ?? report.error ?? ""}`);
      },
    },
    context,
  );
  return { harness };
}

// ---------------------------------------------------------------------------
// watch: durable supervisor task を動かし続ける
// ---------------------------------------------------------------------------
async function cmdWatch(args) {
  const targetEpoch = Number(args.target ?? process.env.I7_COPILOT_TARGET);
  if (!Number.isFinite(targetEpoch) || targetEpoch <= 0) {
    console.error("watch には --target <epoch>（終了 UNIX 時刻）が必要です");
    process.exit(2);
  }
  const intervalSec = Number(args.interval ?? process.env.I7_COPILOT_INTERVAL ?? 600);
  const faux = Boolean(args.faux);
  const modelRef = faux
    ? { provider: "faux", modelId: "faux-1" }
    : splitModelRef(args.model ?? process.env.I7_COPILOT_MODEL ?? "anthropic/claude-sonnet-4-6");
  const dbPath = args.db ?? DB_PATH;

  const prompt = readFileSync(PROMPT_PATH, "utf8");
  const { harness } = await openHarness({ dbPath, faux });

  const root = await harness.root(context, {
    agent: {
      model: modelRef,
      instructions: prompt,
      extensions: { add: [CopilotTools, SupervisorExt] },
      maxTurns: 12,
    },
  });

  // 既存の生存タスクがあれば再利用（再起動で二重起動しない）
  const existing = await harness.inspect(context);
  let taskId;
  const live = existing.tasks.find((t) => t.record.kind === "i7.supervise");
  if (live) {
    taskId = live.record.id;
    console.log(`[copilot] 既存タスクを再開: ${taskId} (state=${live.state.kind})`);
  } else {
    taskId = await harness.commit(async (tx) => {
      return await tx.createTask(
        SupervisorTask,
        {
          targetEpoch,
          intervalSec,
          firstDelayMs: Number(args.first_delay ?? 5000),
          attempt: Date.now(),
          promptPath: PROMPT_PATH,
        },
        { ownership: { kind: "conversation" }, conversationId: root.id },
      );
    }, context);
    console.log(`[copilot] supervisor task 作成: ${taskId} target=${new Date(targetEpoch * 1000).toISOString()} interval=${intervalSec}s model=${modelRef.provider}/${modelRef.modelId}`);
  }

  harness.resume();
  const settled = await harness.waitForTask(taskId, context);
  const outcome = settled.state.status === "terminal" ? settled.state.outcome : undefined;
  console.log(`[copilot] task ended: ${JSON.stringify(outcome ?? settled.state)}`);
  await harness.close(context).catch(() => {});
}

// ---------------------------------------------------------------------------
// once: 1サイクルだけ（faux/実モデル問わず会話を1回だけ動かす）
// ---------------------------------------------------------------------------
async function cmdOnce(args) {
  const faux = Boolean(args.faux);
  const modelRef = faux
    ? { provider: "faux", modelId: "faux-1" }
    : splitModelRef(args.model ?? process.env.I7_COPILOT_MODEL ?? "anthropic/claude-sonnet-4-5");
  const dbPath = args.db ?? join(COPILOT_DIR, `data/once-${Date.now()}.sqlite`);
  const prompt = readFileSync(PROMPT_PATH, "utf8");
  const { harness } = await openHarness({ dbPath, faux });
  const root = await harness.root(context, {
    agent: { model: modelRef, instructions: prompt, extensions: { add: [CopilotTools, SupervisorExt] }, maxTurns: 12 },
  });
  const sub = await root.submit(
    {
      type: "input",
      requestId: `once-${Date.now()}`,
      content: "監視サイクル #1。check_status から始めて、判断表に従って必要なら介入し、最後に1行の状態報告を書いてください。",
    },
    context,
  );
  const settled = await sub.wait(context);
  console.log(`[copilot][once] settled: ${settled.status}${settled.status === "unanswered" ? ` reason=${settled.reason} detail=${JSON.stringify(settled.detail)}` : ""}`);
  if (settled.status === "done" && settled.answer !== undefined) {
    const page = await root.entries({ maxEntryId: settled.answer, order: "descending" }, 1, undefined, context);
    const entry = page.items[0];
    for (const m of entry?.model ?? []) {
      if (m.role === "assistant") {
        for (const c of m.content ?? []) if (c.type === "text") console.log(c.text);
      }
    }
  }
  await harness.close(context).catch(() => {});
}

// ---------------------------------------------------------------------------
const args = parseArgs(process.argv.slice(2));
const cmd = args._[0];
if (!cmd || args.help) {
  console.log(USAGE);
  process.exit(cmd ? 0 : 2);
}
try {
  if (cmd === "watch") await cmdWatch(args);
  else if (cmd === "once") await cmdOnce(args);
  else {
    console.error(`unknown command: ${cmd}\n${USAGE}`);
    process.exit(2);
  }
} catch (e) {
  console.error(`[copilot] fatal: ${e?.stack ?? e}`);
  process.exit(1);
}
