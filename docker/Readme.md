# Docker container

A simple docker container with a NATS jetstream enabled server is provided by a compose file.

## Prerequisites

A Docker network named `backend` is required, so that other Docker containers can connect to the NATS server.
Check the exising Docker networks by running `docker network ls`.
In case there is no `backend` available yet, run `docker network create backend` to create it.

## Create a container

Enter the `docker` directory and bring the container up detached.
```bash
docker compose up -d
```

## Add a JetStream

This command will add a JetStream to the NATS server and subscribe to the subject pattern `events.>`.

```bash
docker run --network host --rm -it natsio/nats-box:latest nats stream add --subjects="events.>" --default
s bluesky
```

Check the existance of the JetStream by running

```bash
docker run --network host --rm -it natsio/nats-box:latest nats stream report
```

The responce should be
```bash
╭──────────────────────────────────────────────────────────────────────────────────────────╮
│                                       Stream Report                                      │
├─────────┬─────────┬───────────┬───────────┬──────────┬───────┬──────┬─────────┬──────────┤
│ Stream  │ Storage │ Placement │ Consumers │ Messages │ Bytes │ Lost │ Deleted │ Replicas │
├─────────┼─────────┼───────────┼───────────┼──────────┼───────┼──────┼─────────┼──────────┤
│ bluesky │ File    │           │         0 │ 0        │ 0 B   │ 0    │       0 │          │
╰─────────┴─────────┴───────────┴───────────┴──────────┴───────┴──────┴─────────┴──────────╯
```
