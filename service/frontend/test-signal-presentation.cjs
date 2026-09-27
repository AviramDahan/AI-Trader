const ts = require('typescript')
const fs = require('node:fs')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const code = ts.transpileModule(fs.readFileSync('src/signalPresentation.ts', 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText
const context = {exports:{}}
vm.runInNewContext(code, context)
const {positionMove, unifiedSignals} = context.exports
assert.equal(positionMove({status:'open', entry_price:100,current_price:110}).toFixed(2),'10.00')
assert.equal(positionMove({status:'open', entry_price:100,current_price:90}).toFixed(2),'-10.00')
for (const price of [null, 0, NaN, Infinity]) assert.equal(positionMove({status:'open',entry_price:100,current_price:price}),null)
assert.equal(positionMove({status:'closed',entry_price:100,current_price:110}),null)
assert.equal(positionMove({status:'open',entry_price:100,last_price:100}),0)
const result=unifiedSignals([{id:1},{id:2},{id:3}], [{id:9,signal_id:1,status:'open'},{id:10,signal_id:2,status:'closed'},{id:11,signal_id:3,status:'open',is_shadow:1},{id:12,status:'open',legacy_position_id:8}],()=>true)
assert.equal(result.open.length,2)
assert.equal(result.closed.length,1)
assert.equal(result.waiting.length,1)
assert.equal(result.waiting[0].id,3)
console.log('Signal presentation: returns, dedupe, legacy, shadow and closed-state PASS')
