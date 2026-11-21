const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function harness() {
    const nodes = new Map();
    function node(sel) {
        if (!nodes.has(sel)) {
            nodes.set(sel, {
                style: {display: ''}, textContent: '', className: '',
                value: '', disabled: false, onclick: null
            });
        }
        return nodes.get(sel);
    }
    const ctx = vm.createContext({
        document: {querySelector: node, querySelectorAll: () => []},
        window: {location: {reload() {}}}, console, setTimeout, setInterval,
        clearInterval, Date,
    });
    const file = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
    const boot = file.lastIndexOf('\nshell();');
    assert(boot > 0);
    vm.runInContext(file.slice(0, boot), ctx);
    return {ctx, node};
}

test('new update displays a notice and Download button', () => {
    const {ctx, node} = harness();
    vm.runInContext("renderUpdateState({status:'available',message:'New release',changed:['app.js'],latest_sha:'abc123'})", ctx);
    assert.equal(node('#updateNotice').style.display, 'inline-flex');
    assert.equal(node('#downloadUpdate').style.display, 'inline-flex');
    assert.equal(node('#applyUpdate').style.display, 'none');
    assert.match(node('#updateDetails').textContent, /app.js/);
});

test('verified update offers restart but not another download', () => {
    const {ctx, node} = harness();
    vm.runInContext("renderUpdateState({status:'ready',message:'Verified',percent:100})", ctx);
    assert.equal(node('#applyUpdate').style.display, 'inline-flex');
    assert.equal(node('#downloadUpdate').style.display, 'none');
    assert.match(node('#updateNotice').textContent, /RESTART/);
});

test('downloading shows stage progress and hides installation action', () => {
    const {ctx, node} = harness();
    vm.runInContext("renderUpdateState({status:'downloading',percent:70,message:'Verifying'})", ctx);
    assert.equal(node('#updateProgress').style.display, 'block');
    assert.equal(node('#updateProgress').value, 70);
    assert.equal(node('#applyUpdate').style.display, 'none');
});

test('updater failure remains readable and never offers install', () => {
    const {ctx, node} = harness();
    vm.runInContext("renderUpdateState({status:'error',message:'Private repository needs gh auth login'})", ctx);
    assert.match(node('#updateStatus').textContent, /gh auth login/);
    assert.equal(node('#applyUpdate').style.display, 'none');
    assert.equal(node('#updateNotice').style.display, 'none');
});

test('Download button requests local download endpoint only', async () => {
    const {ctx, node} = harness();
    ctx.apiCalls = [];
    vm.runInContext("api=async(path,opt)=>{apiCalls.push([path,opt]);return {status:'downloading',percent:5}};bindUpdateControls()",ctx);
    await node('#downloadUpdate').onclick();
    assert.equal(ctx.apiCalls.length, 1);
    assert.equal(ctx.apiCalls[0][0], '/api/updates/download');
    assert.equal(ctx.apiCalls[0][1].method, 'POST');
});

test('Check button requests a forced check, not automatic install', async () => {
    const {ctx, node} = harness();
    ctx.apiCalls = [];
    vm.runInContext("api=async(path,opt)=>{apiCalls.push(path);return {status:'checking',message:'Checking'}};bindUpdateControls()",ctx);
    await node('#checkUpdates').onclick();
    assert.equal(ctx.apiCalls[0], '/api/updates/check?force=1');
    assert.ok(!ctx.apiCalls.some(x => x.includes('/apply')));
});
