import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const files = readdirSync('dist/assets').filter((name) => /\.(js|css)$/.test(name));
const debugOnly = [
  '/__local-preview/',
  '打开原视频与分析 JSON',
  '本地文件设置',
  '.local-files',
  '.local-review',
];
for (const name of files) {
  const contents = readFileSync(resolve('dist/assets', name), 'utf8');
  for (const token of debugOnly) {
    if (contents.includes(token))
      throw new Error(`Development UI leaked into production: ${name} (${token})`);
  }
}
console.log('Production assets exclude local import and experiment data endpoints.');
