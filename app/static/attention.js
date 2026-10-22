/* Builds a read-only view of the existing feeds. Never writes to either app. */
(function (root) {
  "use strict";
  const bookingGroups = {
    overdue_payments: [1, "Review overdue invoice"],
    new_enquiries: [2, "Review new enquiry"],
    accepted_payment: [2, "Review first payment"],
    quotes_waiting: [3, "Quote awaiting a decision"],
    forms_waiting: [3, "Booking form outstanding"],
    agreements_waiting: [3, "Agreement outstanding"],
    payments_due: [3, "Review upcoming invoice"]
  };
  const plannerGroups = {
    invitation_problems: [1, "Review invitation delivery"],
    expiring_access: [3, "Access ends within 14 days"],
    awaiting_couples: [3, "Invitation awaiting couple"]
  };
  function build({tasks = [], booking, planner, today, now = Date.now()}) {
    const items = [], sources = [];
    for (const task of tasks.filter(task => !task.completed)) {
      const overdue = task.due_date && task.due_date < today;
      items.push({id: `task:${task.id}`, source: "Tasks", title: task.title,
        reason: overdue ? "Overdue task" : task.due_date === today ? "Task due today" : task.priority === "high" ? "High priority task" : "Personal task",
        priority: overdue ? 1 : task.priority === "high" || task.due_date === today ? 2 : 3,
        due: task.due_date || null, workspace: task.workspace, taskId: task.id, url: task.url});
    }
    for (const [name, result, groups] of [["Booking", booking, bookingGroups], ["Planner", planner, plannerGroups]]) {
      const source = {name, status: result?.status || "loading", generated_at: result?.data?.generated_at,
        message: result?.message || "", limited: []};
      if (source.status === "connected" && source.generated_at && now - Date.parse(source.generated_at) > 300000) {
        source.status = "stale";
        source.message = "Saved information is more than five minutes old.";
      }
      sources.push(source);
      if (!result?.data) continue;
      for (const [key, [priority, reason]] of Object.entries(groups)) {
        const group = result.data.queues[key];
        const rows = name === "Booking" ? group.items : group;
        const count = name === "Booking" ? group.count : result.data.counts[key];
        if (count > rows.length) source.limited.push({queue: key, shown: rows.length, count});
        rows.forEach((row, index) => items.push({
          id: `${name}:${key}:${index}`, source: name, title: row.title, reason,
          detail: name === "Planner" ? row.status : row.venue,
          priority, due: name === "Planner" ? row.access_until : row.due_date || row.event_date,
          dueLabel: name === "Planner" ? "Access until" : row.due_date ? "Invoice due" : "Wedding",
          amount: row.amount_pence, amountLabel: key === "accepted_payment" ? "First payment" : "Invoice balance", url: result.source_url + row.path,
          stale: source.status !== "connected"
        }));
      }
    }
    items.sort((a, b) => a.priority - b.priority ||
      (a.due || "9999").localeCompare(b.due || "9999") ||
      a.title.localeCompare(b.title, "en-GB") || a.id.localeCompare(b.id));
    return {items, sources};
  }
  const api = {build};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DashboardAttention = api;
})(globalThis);
