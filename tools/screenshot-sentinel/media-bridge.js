const chokidar = require('chokidar');
const path = require('path');
const fs = require('fs');
const clipboardy = require('clipboardy');

const toInt = (v, fallback) => {
  const n = Number.parseInt(String(v ?? ''), 10);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
};

const splitList = (v) =>
  String(v ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

const normalizeExt = (ext) => {
  const e = String(ext ?? '').trim().toLowerCase();
  if (!e) return '';
  return e.startsWith('.') ? e : `.${e}`;
};

const parseArgs = (argv) => {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const cur = argv[i];
    if (!cur.startsWith('--')) continue;
    const key = cur.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      args[key] = next;
      i++;
    } else {
      args[key] = true;
    }
  }
  return args;
};

const args = parseArgs(process.argv);

const WATCH_DIR = path.resolve(
  args.dir || process.env.WATCH_DIR || path.join(process.cwd(), 'screenshots')
);
const MAX_FILES = toInt(args.max || process.env.MAX_FILES, 15);
const ALLOWED_EXTS = (
  (args.ext ? splitList(args.ext) : splitList(process.env.ALLOWED_EXTS)).length
    ? (args.ext ? splitList(args.ext) : splitList(process.env.ALLOWED_EXTS))
    : ['.png', '.jpg', '.jpeg', '.mp4', '.gif']
).map(normalizeExt);

const PATH_KIND = String(args.path || process.env.PATH_KIND || 'relative').toLowerCase();
const PATH_STYLE = String(args.style || process.env.PATH_STYLE || 'posix').toLowerCase();
const CLIPBOARD_ENABLED =
  !args['no-clipboard'] && String(process.env.CLIPBOARD ?? '1') !== '0';
const QUIET = Boolean(args.quiet) || String(process.env.QUIET ?? '0') === '1';

const ensureDir = async () => {
  try {
    await fs.promises.mkdir(WATCH_DIR, { recursive: true });
  } catch {}
};

const formatPath = (filePath) => {
  const abs = path.resolve(filePath);
  const rel = path.relative(process.cwd(), abs) || path.basename(abs);

  let out = PATH_KIND === 'absolute' ? abs : rel;
  if (PATH_STYLE === 'posix') out = out.replaceAll('\\', '/');
  if (PATH_STYLE === 'native') out = out;
  if (PATH_STYLE === 'win') out = out.replaceAll('/', '\\');
  return out;
};

const autoGC = async () => {
  let names;
  try {
    names = await fs.promises.readdir(WATCH_DIR);
  } catch {
    return;
  }

  const items = await Promise.all(
    names.map(async (name) => {
      const p = path.join(WATCH_DIR, name);
      try {
        const st = await fs.promises.stat(p);
        if (!st.isFile()) return null;
        const ext = path.extname(name).toLowerCase();
        if (!ALLOWED_EXTS.includes(ext)) return null;
        return { name, path: p, mtimeMs: st.mtimeMs };
      } catch {
        return null;
      }
    })
  );

  const files = items.filter(Boolean).sort((a, b) => b.mtimeMs - a.mtimeMs);
  if (files.length <= MAX_FILES) return;

  const expired = files.slice(MAX_FILES);
  await Promise.all(
    expired.map(async (f) => {
      try {
        await fs.promises.unlink(f.path);
        if (!QUIET) console.log(`[GC] ${f.name}`);
      } catch {}
    })
  );
};

const main = async () => {
  await ensureDir();

  if (!QUIET) {
    console.log('');
    console.log('截图哨兵已启动');
    console.log(`监控目录: ${WATCH_DIR}`);
    console.log(`保留数量: ${MAX_FILES}`);
    console.log(`允许扩展: ${ALLOWED_EXTS.join(', ')}`);
    console.log(`路径输出: ${PATH_KIND}/${PATH_STYLE}`);
    console.log(`剪贴板: ${CLIPBOARD_ENABLED ? '开启' : '关闭'}`);
    console.log('');
  }

  chokidar
    .watch(WATCH_DIR, {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 800, pollInterval: 100 },
    })
    .on('add', async (filePath) => {
      const ext = path.extname(filePath).toLowerCase();
      if (!ALLOWED_EXTS.includes(ext)) return;

      const outPath = formatPath(filePath);
      if (!QUIET) {
        console.log('-------------------------------------------');
        console.log(`新捕获: ${path.basename(filePath)}`);
        console.log(`路径: ${outPath}`);
      }

      if (CLIPBOARD_ENABLED) {
        try {
          await clipboardy.write(outPath);
          if (!QUIET) console.log('已写入剪贴板');
        } catch {
          if (!QUIET) console.log('剪贴板写入失败');
        }
      }

      await autoGC();
    });
};

main().catch(() => process.exitCode = 1);
