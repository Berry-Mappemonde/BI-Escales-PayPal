import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const scriptUrl = new URL('./revue-locale-nim.sh', import.meta.url);

test('the API environment disables dotenv and excludes Token Factory', async () => {
  const script = await readFile(scriptUrl, 'utf8');
  const apiLaunch = script.match(
    /env -u NEBIUS_API_KEY -u NAVIGUIDE_OFFLINE -u NAVIGUIDE_LLM_MODE[\s\\]*\n([\s\S]*?)\/workspace\/nv-venv\/bin\/python -m uvicorn/
  );

  assert.ok(apiLaunch, 'API launch must explicitly construct its environment');
  assert.match(apiLaunch[0], /PYTHON_DOTENV_DISABLED=1/);
  assert.match(apiLaunch[0], /NAVIGUIDE_LLM_PROVIDERS=nim/);
  assert.match(apiLaunch[0], /NVIDIA_API_KEY="\$NVIDIA_API_KEY_2"/);
  assert.doesNotMatch(apiLaunch[0], /(?:^|\s)NEBIUS_API_KEY=/);
  assert.match(apiLaunch[0], /env -u NEBIUS_API_KEY/);
});
