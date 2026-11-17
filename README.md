# agenttradr.com uptime probe

Every 10 minutes GitHub Actions checks `https://agenttradr.com/api/v1/health` and
`https://agenttradr.com/api/v1/public/status` from outside our servers. A failed run turns red, GitHub emails the
owner, and a Pushover goes out (first failure, then after 1 h, 3 h and 6 h, and once on recovery).
