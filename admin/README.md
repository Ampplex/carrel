# Admin console — Reeve + Carrel

One page answering "what is the state of both systems", built because the data
lives in two stores that know nothing about each other: Carrel's accounts in
Postgres, Reeve's graph and plans in Neo4j.

## Reaching it

It has no public address. It is published on `127.0.0.1:8020` and is not proxied
by nginx, so it is reachable only from the server itself — or through an SSH
tunnel from a laptop:

    ssh -i ~/reeve.pem -L 8020:127.0.0.1:8020 ubuntu@13.127.158.249
    open http://localhost:8020

The SSH key is the authentication. That is deliberate: a password on this page
would be one more secret to invent, store and eventually leak, and it would
protect something that is already behind a key you hold.

## What it shows

Counts, dates and account identifiers. **No memory contents** — not a note, not
a caption, not a message. The privacy policy shipped with Carrel says a person's
memories are theirs; an admin console that quietly made them readable would turn
that into a convenient lie. Everything operational (is anyone signing up, is a
write stuck, is anything failing) is answerable from counts.

## What it does not do

It is read-only. No delete, no plan override, no key revocation. Those need to
sit behind stronger authentication than "whoever reached this page", and adding
them without that would be the wrong order.

## Running it

    docker compose -p carrel up -d admin

Config comes from `admin/.env` (see `.env.example`), which is gitignored: it
carries the Postgres URL and the Neo4j Aura password.
