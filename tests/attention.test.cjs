const {test} = require('node:test');
const assert = require('node:assert/strict');
const {build} = require('../app/static/attention.js');
const now = Date.parse('2026-10-22T12:00:00Z');
function feeds() {
  const booking = {status:'connected', source_url:'https://booking.example', data:{generated_at:new Date(now).toISOString(),queues:{}}};
  for (const key of ['overdue_payments','new_enquiries','accepted_payment','quotes_waiting','forms_waiting','agreements_waiting','payments_due']) {
    booking.data.queues[key] = {count:0,items:[]};
  }
  const planner = {status:'connected', source_url:'https://planner.example', data:{generated_at:new Date(now).toISOString(),counts:{},queues:{}}};
  for (const key of ['invitation_problems','awaiting_couples','expiring_access']) {
    planner.data.queues[key] = []; planner.data.counts[key] = 0;
  }
  return {booking,planner,today:'2026-10-22',now};
}
function bookingRow() { return {title:'Alex & Sam',path:'/bookings/123/payments',due_date:'2026-10-20',amount_pence:12000}; }

test('urgent actions from all three sources precede normal follow-ups; completed tasks disappear', () => {
  const input=feeds();
  input.booking.data.queues.overdue_payments={count:1,items:[bookingRow()]};
  input.planner.data.queues.invitation_problems=[{title:'Taylor & Jo',access_until:'2027-01-01',path:'/ivoryadmin',status:'Email failed'}];
  input.planner.data.counts.invitation_problems=1;
  input.tasks=[{id:1,title:'Tomorrow',due_date:'2026-10-23'}, {id:2,title:'Overdue task',due_date:'2026-10-19'},
    {id:3,title:'Already done',completed:1,due_date:'2020-01-01'}, {id:4,title:'High priority',priority:'high'}];
  const original=JSON.stringify(input);
  const result=build(input);
  assert.deepEqual(result.items.map(row=>row.title), ['Overdue task','Alex & Sam','Taylor & Jo','High priority','Tomorrow']);
  assert.deepEqual(result.items.map(row=>row.priority), [1,1,1,2,3]);
  assert.equal(JSON.stringify(input),original,'combining must not change source data');
  assert.equal(result.items[1].url,'https://booking.example/bookings/123/payments');
});

test('each action is retained when the same wedding occurs in multiple queues or apps', () => {
  const input=feeds();
  for (const key of Object.keys(input.booking.data.queues)) input.booking.data.queues[key]={count:1,items:[bookingRow()]};
  for (const key of Object.keys(input.planner.data.queues)) {
    input.planner.data.queues[key]=[{title:'Alex & Sam',access_until:'2026-10-25',path:'/ivoryadmin',status:'Awaiting couple'}];
    input.planner.data.counts[key]=1;
  }
  const result=build(input);
  assert.equal(result.items.length,10);
  assert.equal(new Set(result.items.map(row=>row.id)).size,10);
});

test('queue totals beyond the supplied previews are exposed instead of claiming completeness', () => {
  const input=feeds();
  input.booking.data.queues.quotes_waiting={count:17,items:[bookingRow()]};
  input.planner.data.counts.expiring_access=6;
  input.planner.data.queues.expiring_access=[{title:'Example',access_until:'2026-10-25',path:'/ivoryadmin'}];
  const result=build(input);
  assert.equal(result.items.length,2);
  assert.deepEqual(result.sources[0].limited,[{queue:'quotes_waiting',shown:1,count:17}]);
  assert.deepEqual(result.sources[1].limited,[{queue:'expiring_access',shown:1,count:6}]);
});

test('unavailable feeds do not hide personal tasks; missing sources are explicitly loading', () => {
  const result=build({today:'2026-10-22',booking:{status:'error',message:'Cannot refresh',data:null},tasks:[{id:1,title:'Task'}]});
  assert.equal(result.items.length,1);
  assert.deepEqual(result.sources.map(source=>source.status),['error','loading']);
});

test('cached and aged feeds label every affected action as saved information', () => {
  const input=feeds();
  input.booking.status='stale';
  input.booking.data.queues.overdue_payments={count:1,items:[bookingRow()]};
  input.planner.data.generated_at='2026-10-22T11:54:59Z';
  input.planner.data.queues.expiring_access=[{title:'Example',access_until:'2026-10-25',path:'/ivoryadmin'}];
  input.planner.data.counts.expiring_access=1;
  const result=build(input);
  assert.ok(result.items.every(row=>row.stale));
  assert.deepEqual(result.sources.map(source=>source.status),['stale','stale']);
  assert.match(result.sources[1].message,/five minutes/);
});

test('due today and high priority are next; undated tasks follow dated tasks in their band', () => {
  const input=feeds();
  input.tasks=[{id:1,title:'Undated'}, {id:2,title:'Due today',due_date:'2026-10-22'},
    {id:3,title:'High priority',priority:'high',due_date:'2026-10-24'}, {id:4,title:'Dated',due_date:'2026-10-25'}];
  assert.deepEqual(build(input).items.map(row=>row.taskId),[2,3,4,1]);
});

test('first payment amounts remain distinguishable from outstanding invoice balances', () => {
  const input=feeds();
  input.booking.data.queues.accepted_payment={count:1,items:[bookingRow()]};
  input.booking.data.queues.overdue_payments={count:1,items:[bookingRow()]};
  const result=build(input);
  assert.deepEqual(result.items.map(row=>row.amountLabel), ['Invoice balance','First payment']);
});
