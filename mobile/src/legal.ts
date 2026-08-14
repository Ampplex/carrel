/**
 * The terms and the privacy notice, as data.
 *
 * They live in the app rather than behind a link for one practical reason:
 * Carrel has no website. The backend runs on a machine on your network, and a
 * "read the terms" link pointing at a URL that does not exist is worse than no
 * link at all. Shipped text also means the document matches the build you are
 * actually running.
 *
 * Everything below is written to match what the code does — same stores, same
 * third party, same gaps. Where something is missing (no password reset, no
 * email verification, plain HTTP on a local network) it is stated rather than
 * quietly omitted, because a privacy notice that describes a better system than
 * the one you installed is the specific failure these documents exist to avoid.
 *
 * `LEGAL_VERSION` is recorded against an account when it is created, so there
 * is a record of which wording somebody actually agreed to. Change the text,
 * change the date.
 */

export const LEGAL_VERSION = "2026-08-14";

export type Section = { heading: string; body: string };

export type LegalDoc = {
  key: "terms" | "privacy";
  tab: string;
  title: string;
  intro: string;
  sections: Section[];
};

export const TERMS: LegalDoc = {
  key: "terms",
  tab: "Terms",
  title: "Terms of Use",
  intro:
    "Carrel is a student project, not a commercial service. These terms are short because the arrangement is simple: you keep notes here, and you can take them back at any time.",
  sections: [
    {
      heading: "1. What Carrel is",
      body:
        "Carrel stores what you tell it — typed notes and photographs — so you can ask about it later in plain language. It is provided as it is, with no guarantee that it works, stays available, or keeps your data intact. The deployment you are using may be reset, moved, or switched off, and there is no service level behind it.",
    },
    {
      heading: "2. Your account",
      body:
        "You are responsible for the email and password you choose and for anything done with them. Two limits are worth knowing before you sign up: there is no password reset, and email addresses are not verified. If you forget your password, the account cannot be recovered — you would start again with a new one. A sign-in lasts thirty days on a device before it has to be repeated.",
    },
    {
      heading: "3. What you should put in it",
      body:
        "Only things you are comfortable placing on a server you do not control. Carrel is a good place for lecture notes, deadlines, meeting decisions, whiteboards and receipts. It is not the place for passwords, financial or medical records, material covered by an employer's confidentiality rules, or other people's personal details recorded without their knowledge.",
    },
    {
      heading: "4. What you may not do",
      body:
        "Do not use Carrel to store or generate unlawful material, to impersonate somebody else, or to reach another account's data. Each account is partitioned from every other; attempting to cross that boundary is misuse, not research.",
    },
    {
      heading: "5. Your notes are yours",
      body:
        "You keep every right you had in what you write and photograph. Carrel is given only the permission it needs to do the job — to store your material, send it to the memory service described in the privacy notice, and show it back to you. It is not sold, not shown to other users, and not used for advertising.",
    },
    {
      heading: "6. Ending it",
      body:
        "Settings has two exits. Erase everything empties the account and leaves you signed in; Delete my account does the same and then removes the login. Both take effect immediately, everywhere, with no grace period and no copy kept back.",
    },
    {
      heading: "7. Age",
      body:
        "You need to be at least 13, and old enough where you live to agree to terms like these on your own behalf.",
    },
    {
      heading: "8. Liability",
      body:
        "To the extent the law allows, Carrel comes with no warranties and its authors are not liable for lost data or for anything that follows from using it. Keep your own copy of anything you cannot afford to lose. This is a coursework project rather than a lawyer-drafted commercial agreement, and it should be read that way.",
    },
    {
      heading: "9. Changes",
      body:
        "These terms carry the date they were last changed. The current version always ships inside the app and is readable from Settings; there is no separate copy elsewhere that could quietly differ from this one.",
    },
  ],
};

export const PRIVACY: LegalDoc = {
  key: "privacy",
  tab: "Privacy",
  title: "Privacy Policy",
  intro:
    "The short version: Carrel keeps what you give it and nothing else. There are no analytics, no trackers, no advertising identifiers, and nothing is collected in the background.",
  sections: [
    {
      heading: "What is collected",
      body:
        "Your email address, a name if you supply one, and your password stored only as a scrypt hash — the password itself is never written down. Then the material you deliberately provide: the messages you type, the photographs you attach, and the times each was recorded.",
    },
    {
      heading: "What is not collected",
      body:
        "No location, contacts, calendar, microphone, or camera roll access beyond the single photograph you pick for a message. No usage analytics or crash telemetry. No advertising or device identifiers. Carrel has no notion of who else uses it, and does not try to build one.",
    },
    {
      heading: "Where it goes",
      body:
        "Notes and photographs are sent to Reeve, the memory service Carrel is built on, which indexes them so they can be found later. Reeve stores data on servers in Mumbai, India, and keeps the original photograph rather than only a description of it — that is what makes it possible to answer a question months later about a detail nobody thought to write down at the time. Carrel's own backend additionally keeps a local copy of each photograph for thumbnails, and your conversation transcripts, on the machine it runs on.",
    },
    {
      heading: "Automated processing",
      body:
        "To answer you, your text and photographs are read by the language and vision models Reeve calls. Carrel does not use your data to train any model. Those services handle it under their own terms, which Carrel does not control.",
    },
    {
      heading: "Who can reach it",
      body:
        "Every account is given its own partition, and the app never lets a client name somebody else's — the partition is derived from your sign-in, so a request can only reach the memory belonging to whoever holds the token. Nothing is shared with other users. Whoever operates the backend you are connected to has access to the disk it runs on, so trust that person as much as you trust the notes.",
    },
    {
      heading: "How long it is kept",
      body:
        "Until you delete it. Nothing expires on its own, and photographs in particular are kept indefinitely so they remain re-readable.",
    },
    {
      heading: "Deleting it",
      body:
        "Settings → Erase everything removes your memories, the photographs Reeve retained, Carrel's local copies, and every conversation. Delete my account does all of that and then removes the login and its sessions. Both run against the memory service first, so nothing local is destroyed unless the remote erasure actually succeeded, and the app tells you exactly what went.",
    },
    {
      heading: "Security, honestly",
      body:
        "Passwords are hashed with scrypt and sign-in tokens are held in the device keychain. But there is no email verification, no password reset, and no rate limiting on sign-in attempts, and when the backend runs on a home or campus network the connection between app and server is plain HTTP rather than HTTPS — anyone on that network could read it in transit. These are known gaps in a project build, listed here rather than left for you to find out.",
    },
    {
      heading: "Your choices",
      body:
        "You can sign out, erase your data, or delete the account entirely, at any time, from Settings. There is no retention period to wait out and nothing to email anybody to request.",
    },
    {
      heading: "Contact",
      body:
        "Carrel is operated by whoever runs the backend you are pointed at. For anything about this notice, ask them.",
    },
  ],
};

export const LEGAL_DOCS: LegalDoc[] = [TERMS, PRIVACY];
