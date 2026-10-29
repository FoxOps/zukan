# Security policy

Thank you for helping keep Zukan and its users safe. Security reports and
constructive reviews are welcome, including findings about the server, web
interface, Android app, authentication, and deployment configuration supplied by
the project.

## Reporting a vulnerability

**Please report suspected security vulnerabilities privately.** Do not include
exploitation details, credentials, or private data in a public issue, discussion,
or pull request.

Use GitHub's [private vulnerability reporting form](https://github.com/FoxOps/zukan/security/advisories/new).
You can also find it through the repository's **Security** tab, under
**Advisories → Report a vulnerability**.

If private reporting is unavailable, open an issue titled **"Private security
contact requested"** and ask how to contact the maintainer privately. Include no
vulnerability details, affected endpoints, proof of concept, logs, or screenshots
in that public issue. Wait for a private channel before sharing the report.

Ordinary bugs and feature requests can use the
[issue templates](https://github.com/FoxOps/zukan/issues/new/choose). If you are
unsure whether a problem has security implications, report it privately first.

## What to include

Provide as much of the following as you can:

- A short summary and the affected component.
- The affected version or commit, and relevant environment details.
- Required conditions, such as configuration, authentication, user role, or
  network access.
- Reproduction steps and, where useful, a minimal proof of concept using test data.
- The observed behavior and potential impact on confidentiality, integrity, or
  availability.
- Relevant sanitized logs or screenshots.
- Any suggested mitigation or fix, if you have one.

For example, relevant findings may involve access to another user's collection,
authentication or authorization bypasses, injection, unsafe file handling,
server-side request forgery, or exposure of secrets.

You do not need a complete exploit or a proposed fix to report a credible concern.
Clearly distinguish what you verified from what you suspect. Never send working
passwords, tokens, session cookies, or other users' private data as evidence.

## Versions and fixes

Security maintenance focuses on the **latest stable release**. Older releases
do not have a separate security maintenance or guaranteed backport policy.
When no stable release exists, maintenance focuses on the default branch.

Reports affecting development versions are welcome too. State the exact commit
or prerelease version so the issue can be investigated accurately.

When practical, check whether a newer version already addresses the problem.
You do not need to upgrade a production instance or delay a report to do this.
Published fixes, affected versions, and available mitigations will be documented
in [security advisories](https://github.com/FoxOps/zukan/security/advisories)
and relevant [release notes](https://github.com/FoxOps/zukan/releases).

## Review and coordinated disclosure

Zukan is a personal project with limited maintenance capacity. Reports will be
reviewed as availability allows; there is no guaranteed response or resolution
deadline. The aim is to understand the impact, reproduce the issue, and prepare
a fix or practical mitigation.

Please keep discussion in the private report and allow time to coordinate a fix
and disclosure. Avoid opening a public fix that reveals an unresolved vulnerability
before that coordination. If the matter is urgent or you have a disclosure
deadline, explain it in the private report. You may follow up there if you have
not received a response.

Reporter credit can be included in an advisory if you want it. Tell the maintainer
how you would like to be credited, or if you prefer to remain anonymous.

## Testing responsibly

Use a local or isolated instance with test accounts and synthetic collection data
whenever possible. Test only systems you own or have explicit authorization to
assess. This policy does not authorize testing the maintainer's public instance,
other users' deployments, identity providers, or third-party data services.

Avoid service disruption, destructive changes, and access to other people's data.
If private information is exposed unexpectedly, stop testing and report the
minimum information needed to explain the issue without copying or retaining
unnecessary data.

## AI-assisted security work

AI tools may help with analysis and fixes. If you use them to produce a report or
patch, disclose their role and personally review the result. State what you have
actually reproduced; an automated or AI-generated finding alone is not proof of
exploitability. Do not send secrets or private user data to AI services.

Security patches follow the project's
[contribution guidelines](https://github.com/FoxOps/zukan/blob/HEAD/CONTRIBUTING.md),
including review, testing, and AI-use disclosure, while keeping vulnerability
details private until disclosure is coordinated.
