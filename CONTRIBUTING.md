# Contributing to Zukan

Thank you for taking an interest in Zukan. Contributions are welcome, whether you
write code, collect cards, translate interfaces, improve documentation, or help
someone understand a problem.

I started Zukan to meet a personal need: managing collections from several trading
card games in one self-hosted application, on both my computer and my phone. I use
AI agents to develop it, and I stand by that choice. Without them, this project
would not have happened.

I also have a lot to learn. Experienced developers are very welcome to help improve
the code and architecture, explain better approaches, and challenge existing
decisions. You do not need to agree with every implementation choice to contribute.
Constructive criticism is welcome.

## What we want to preserve

As Zukan grows, contributions should help preserve these principles:

- **Simple to install and self-host.** Keep deployment, configuration, updates,
  and recovery understandable. Explain any new operational requirements.
- **Usable on a small server.** Consider memory, CPU, storage, and network costs,
  especially for background synchronization, image processing, and large catalogs.
  Avoid adding substantial infrastructure requirements without discussing them first.
- **Independent of vendors and proprietary services.** Prefer open standards,
  replaceable integrations, and user-controlled data. A proprietary integration
  should remain optional, with its limitations clearly explained, rather than
  becoming a requirement for core collection management.
- **An accessible interface as features grow.** Keep common tasks easy to find and
  understand. Consider keyboard navigation, readable contrast, clear labels,
  translations, and both mobile and desktop use where relevant.

These principles guide review; they are not a claim that the current implementation
already gets everything right. Improvements to existing shortcomings are welcome.

## Ways to help

- Report bugs with enough information to reproduce them.
- Share feedback about collecting workflows and everyday usability.
- Improve installation instructions, explanations, and troubleshooting guides.
- Translate the interfaces or correct existing translations.
- Fix bugs, improve accessibility, or reduce resource usage.
- Review code, suggest architectural improvements, or explain a technical tradeoff.
- Add support for games, catalogs, or price sources through the provider system.

Small contributions are useful. You do not need to start with a large feature.

## Before you start

Search [existing issues](https://github.com/FoxOps/zukan/issues) and
[pull requests](https://github.com/FoxOps/zukan/pulls) to see whether someone has
already reported the problem or started related work.

For a small fix, you can open a pull request directly. For a new feature, a large
refactor, a new dependency with significant costs, or a change to authentication,
data storage, or deployment, open an issue first. Explain the problem, the proposed
approach, and the likely effect on existing users. This helps us agree on a useful
direction before you spend a lot of time implementing it.

Issues and pull requests should preferably be written in English so more people
can participate. If English is a barrier, French is welcome too.

## Reporting a bug or proposing a feature

For a bug, include:

- The Zukan version or commit, and the affected component: server, web, or Android.
- Relevant environment details, such as your installation method, browser, or
  Android version.
- Steps to reproduce, expected behavior, and actual behavior.
- Relevant logs or screenshots, with passwords, tokens, personal information, and
  private collection data removed.

For a feature, describe the collecting or administration problem you want to solve,
how it would help, and any alternatives you have considered. Mockups and concrete
examples are useful, but a complete technical design is not required.

Do not publish credentials or details that would let someone exploit an unpatched
security vulnerability in a public issue. Use an available private vulnerability
reporting channel on the repository, or contact the maintainer privately through
a published contact channel.

## Development and documentation

Use the [Development guide](https://github.com/FoxOps/zukan/wiki/Development) for
local setup, builds, and checks. The
[Architecture guide](https://github.com/FoxOps/zukan/wiki/Architecture) explains
the main components, and
[Plugin development](https://github.com/FoxOps/zukan/wiki/Plugin-development)
covers game and price providers.

The [wiki](https://github.com/FoxOps/zukan/wiki) is the main documentation. Avoid
duplicating setup instructions that would need to be maintained in several places.
When a change affects documented behavior, identify the affected wiki pages and
include proposed Markdown updates in the pull request description or linked issue
if you cannot edit those pages directly.

Follow the conventions of the code you are changing. Keep unrelated formatting,
renaming, and cleanup out of a focused fix. Explain a different approach when it
would improve the existing code rather than copying a known problem.

## Contributions made with AI tools

AI-assisted and agent-generated contributions are welcome. The same review and
quality expectations apply to all contributions.

If you use AI to produce or materially change code, tests, documentation,
translations, or assets, **disclose that use in the pull request**. Briefly state
which tool or tools you used and what they helped with. Full prompts and private
conversation histories are not required.

Before submitting, you must:

- Read and understand the changes you are proposing.
- Check that they address the actual problem and fit the surrounding code.
- Test the affected behavior and review the results yourself.
- Verify suggested APIs, dependencies, and technical claims.
- Check the origin and licensing of included material; AI output is not evidence
  that material is original or that you have permission to contribute it.

You remain responsible for your submission and should be able to explain it and
respond to review. An agent's statement that a change works does not replace your
own verification. If you need help understanding part of a change, ask before
presenting it as ready to merge.

## Opening a pull request

Keep each pull request focused on one problem or a coherent set of related changes.
Use a draft pull request when you want early feedback or still have work to do.

Include:

- **Problem:** what is broken or missing, with a linked issue when available.
- **Changes:** what the contribution does and any relevant tradeoffs.
- **Verification:** the checks you ran and their results. Describe manual testing
  where relevant, and state clearly what you could not test.
- **User impact:** screenshots for interface changes, and configuration, migration,
  deployment, or documentation changes when applicable.
- **AI use:** the tools used and their role, if applicable.

Run the relevant checks described in the development guide. For a bug fix, add a
regression test when practical. Match verification to the change: documentation
corrections, interface changes, and database migrations need different checks.
Call out destructive migrations or risks to existing collection data explicitly.

For providers and imported data, document the source, supported languages, known
limitations, and any credentials required. Respect source licenses, attribution
requirements, access conditions, and rate limits. Do not include third-party card
images or datasets in the repository unless their redistribution is permitted.

## License and authorship

Zukan is licensed under the
[CeCILL Free Software License Agreement, version 2.1](https://cecill.info/licences/Licence_CeCILL_V2.1-en.html)
(`CECILL-2.1`). Read the license before contributing. This guide does not replace
or amend its terms.

By submitting a contribution for inclusion in Zukan, you agree to make your original
contribution available under CeCILL 2.1. You retain your rights in your contribution;
no copyright assignment or separate contributor license agreement is required.

Only submit material you have the right to contribute. Identify third-party
material, its source, and its license so compatibility can be reviewed. Preserve
applicable copyright, license, and attribution notices.

CeCILL 2.1 requires an explicit notice identifying the author of a contribution and
its creation date. Keep accurate author and date information in your commits and
include appropriate dated authorship notices with your contribution. Preserve
existing notices when modifying files. A GitHub `noreply` address can be used for
your commit email to protect your personal address.

## Working together

Be respectful, specific, and constructive. Discuss the code, the behavior, and the
tradeoffs; avoid personal attacks. Beginners and experienced contributors are both
welcome, and asking questions is encouraged.

The maintainer is responsible for deciding what is merged and for keeping the
project coherent. Feedback can change that decision, and explaining a better
approach is welcome. A useful idea may still need a different implementation,
a smaller scope, or more discussion before it can be accepted.

Zukan is a personal project, so review and support happen as time allows. Opening
an issue or pull request does not guarantee a response time or acceptance.

Thank you for helping make Zukan better.
