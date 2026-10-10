import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { changedMethodSettings as changed } from '../src/utils/votingMethods.js';
let server, Settings;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase110-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const module = await server.ssrLoadModule('/src/components/VotingMethodSettings.jsx');
  Settings = module.default;
});
after(async () => { await server?.close(); });
const render = props => renderToStaticMarkup(createElement(Settings, { onChange() {}, ...props }));
test('inherited controls expose the parent selection and stay locked', () => {
  const inputs = render({ allowed: ['binary', 'score', 'budget_project'], editable: false }).match(/<input[^>]+>/g);
  assert.equal(inputs.length, 9);
  assert.equal(inputs.filter(i => i.includes('disabled')).length, 9);
  assert.equal(inputs.filter(i => i.includes('checked')).length, 3);
  assert.deepEqual(changed(['binary', 'score', 'future'], 'star', true, false), ['binary', 'score', 'future']);
  assert.deepEqual(changed(['binary', 'score'], 'score', false, false), ['binary', 'score']);
});
test('override changes preserve unrelated/future methods and binary', () => {
  const original = ['binary', 'approval', 'future'];
  const updated = changed(original, 'star', true, true);
  assert.deepEqual(updated, ['binary', 'approval', 'future', 'star']);
  assert.deepEqual(changed(updated, 'approval', false, true), ['binary', 'future', 'star']);
  assert.deepEqual(changed(updated, 'binary', false, true), updated);
  assert.deepEqual(original, ['binary', 'approval', 'future']);
  assert.deepEqual(changed(undefined, 'star', true, true), ['binary', 'star']);
});
test('editable settings retain a locked binary with all other controls enabled', () => {
  const inputs = render({ allowed: ['score'] }).match(/<input[^>]+>/g);
  assert.equal(inputs.filter(i => i.includes('disabled')).length, 1);
  assert.match(inputs[0], /checked/);
  assert.equal(inputs.filter(i => i.includes('checked')).length, 2);
});
test('every input has its own label and linked descriptive text', () => {
  const html = render({});
  for (const input of html.match(/<input[^>]+>/g)) {
    const id = input.match(/id="([^"]+)"/)[1];
    const description = input.match(/aria-describedby="([^"]+)"/)[1];
    assert.ok(html.includes(`for="${id}"`));
    assert.ok(html.includes(`id="${description}"`));
    assert.notEqual(id, description);
  }
});
test('grade explanation is a native keyboard/touch disclosure outside checkbox labels', () => {
  const html = render({});
  assert.match(html, /<details[^>]*><summary/);
  assert.match(html, /focus-visible:outline/);
  assert.doesNotMatch(html, /<label[^>]*>[^<]*<details/);
  assert.doesNotMatch(html, /<details[^>]*open/);
});
