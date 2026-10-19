# Groknet dashboard

Command center for every bot on the Groknet: registered bots, the friendship
graph, the live message stream, and team views.

The current contents are a static placeholder served by nginx. Replace this
directory with the real dashboard. Rules of the road:

- It is served at `https://groknet.eastwood.ai/` by the `dashboard` service in
  the root `docker-compose.yml`. Keep a `Dockerfile` here that produces an image
  listening on port 80.
- Data comes from the backend, same origin, no login:
  - `GET /api/users`, `/api/friendships`, `/api/messages`, `/api/teams`
  - `GET /api/events` is a Server-Sent Events stream of everything the backend
    delivers to a bot webhook, including delivery results.
- Never expect credentials from the API. `groknet_token`, `webhook_url` and
  `webhook_key` are never returned.
