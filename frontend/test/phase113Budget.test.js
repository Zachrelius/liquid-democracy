import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { budgetAggregationChoices, chosenBudgetAggregation, toggleBudgetAggregation } from '../src/utils/budgetAggregations.js';
let server, Settings, Selector;
before(async () => {
  server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] }, cacheDir: 'node_modules/.vite-phase113-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  const module = await server.ssrLoadModule('/src/components/BudgetAggregationSettings.jsx');
  Settings = module.default; Selector = module.BudgetAggregationSelector;
});
after(async () => { await server?.close(); });
const render = (component, props) => renderToStaticMarkup(createElement(component, { onChange() {}, ...props }));
test('legacy/fresh/trimmed-only defaults and scope use authoritative values', () => {
  assert.deepEqual(budgetAggregationChoices(), ['median', 'trimmed_mean']);
  assert.equal(chosenBudgetAggregation('', ['trimmed_mean']), 'trimmed_mean');
  assert.deepEqual(budgetAggregationChoices({ allowed_budget_aggregations: ['median'] }, {allowed_budget_aggregations:['trimmed_mean']}), ['median']);
  assert.equal(chosenBudgetAggregation('median', ['trimmed_mean']), 'median');
});
test('single permitted aggregation is read-only text; two produce labeled selector', () => {
  assert.doesNotMatch(render(Selector, {choices:['median'],value:'median'}), /<select/);
  const html = render(Selector, {choices:['median','trimmed_mean'],value:'median'});
  assert.match(html, /<select/); assert.match(html, /<label[^>]+for=/);
  assert.doesNotMatch(html, /strategyproof/);
});
test('grandfathered draft retains its rule with explicit explanation', () => {
  const html = render(Selector, {choices:['median'],value:'trimmed_mean',grandfathered:true});
  assert.match(html, /existing rule retained/); assert.match(html, /different choice must follow/);
});
test('inherited settings lock inputs and describe weighted trimming accurately', () => {
  const html = render(Settings, {choices:['median'],editable:false});
  assert.equal(html.match(/<input[^>]*disabled/g).length,2);
  assert.match(html,/10%/); assert.match(html,/Fewer than five/); assert.match(html,/fraction of a boundary ballot/);
  assert.match(html, /<details/); assert.match(html, /guarantee/);
});
test('parent restrictions and empty-selection error stay visible', () => {
  const html=render(Settings,{choices:[],permitted:['median']});
  assert.match(html,/role="alert"/); assert.match(html,/Restricted by parent/);
  assert.deepEqual(toggleBudgetAggregation(['median'],'trimmed_mean',true),['median','trimmed_mean']);
  assert.deepEqual(toggleBudgetAggregation(['median'],'median',false),[]);
});
