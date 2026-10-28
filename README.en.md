# ARTA-MATRYOSHKA

**ARTA-MATRYOSHKA explores layered deception environments that may redirect automated intruders into repeated, misleading paths.**

It is an experimental research concept and local prototype, not a production-ready security product.
Effectiveness against actual AI attackers has not been validated.
It is shared so developers and security researchers can find inspiration, independently test the idea, and extend it.
Critical feedback, reproducible experiments, improvements, and negative results are welcome.

[한국어](README.md) | **English**

## Why

Access decisions alone do not explain every aspect of intruder exploration and judgment.
When does an intruder mistake a decoy system for a real one?
Will it continue exploring after suspecting deception?
Can changes in exploration time, revisits, and verification behavior be measured?

ARTA-MATRYOSHKA aims to turn these questions into testable experiments.

## Concept

Offer synthetic assets and clues that appear to lead toward a meaningful goal,
then expose further decoy spaces as exploration progresses, like nested matryoshka dolls.
Real protected assets must remain behind independent authentication, access-control, and isolation boundaries.

The current implementation is a **finite decoy world** represented by a JSON HTTP API.
A synthetic recovery code changes simulated state; presets add doors, false exits, and a settings replica.
It does not implement infinite nesting, prevent an intruder from leaving, or perform real privilege escalation or sandbox escape.

## Current status

| Category | What the repository contains |
|---|---|
| Implemented | Loopback-only decoy API, per-session synthetic state, six scenario presets, request and session budgets ([world](arta/world.py), [HTTP](arta/web.py)) |
| Implemented | Separate collector process, authenticated observation, SQLite event storage and hash-chain checks ([collector](arta/collector.py), [store](arta/audit.py)) |
| Implemented, separate experiments | Fixed-script exploration and synthetic collection comparisons with ordinary SHA-256 PoW and rate limiting. PoW is not integrated with the decoy world ([exploration](arta/experiment.py), [collection](arta/collectionbench.py)) |
| Published preliminary evidence | Functional tests, synthetic experiment reports, and raw JSON. These are distinct from actual AI-agent or real-attacker behavioral evaluations |
| Future evaluation | No-decoy controls; actual AI detection, bypass, and abandonment behavior; longer repeats and reproduction in other environments |
| Ideas / not implemented | Strong OS/network isolation, operational integration, external alerts, two-person approval, VDFs, and a graphical dashboard. No implementation schedule is committed |

Cost and collection differences in fixed Python scripts do not establish AI deception or real-asset protection.
The current `baseline` is itself a simple decoy, **not a no-deception control**.
Zero collection from a synthetic protected endpoint that is always denied by construction is not evidence of deception effectiveness.

## Research questions

- Does exploration or time to reach a goal increase versus a no-decoy condition?
- Do mistaken identification of synthetic assets and revisit rates change?
- When do AI agents detect clues, verify, bypass, or leave the environment?
- Do observations from the deception structure provide useful signals to defenders?

Compare the same synthetic goals under matched time, request, and resource budgets.
Measure legitimate-user impact and defender costs as well.
These are research questions, not established outcomes. [Design and evaluation plan, Korean](docs/DESIGN.md)

## Run locally

Python 3.10+; standard library only.
Read the limitations below first and use an authorized, isolated local lab.

```bash
git clone https://github.com/daning1212/ARTA-MATRYOSHKA.git
cd ARTA-MATRYOSHKA
python -m arta
```

Decoy API: http://127.0.0.1:8080 · Observe from another terminal: `python -m arta.observe` · Stop: Ctrl+C.
The default runtime limit is 900 seconds. [Scenarios, responses, and limits](docs/REFERENCE.en.md#run-the-lab)

Functional tests: `python -m unittest discover -s tests -v`. Passing them does not validate security effectiveness.

## Unverified claims and why

- This does not replace firewalls, authentication, access control, or network separation. Actual attacker and AI effectiveness requires repeated evaluation.
- Loopback binding and separate processes do not provide an OS sandbox. The current code does not enforce OS-level restrictions on same-account file access or outbound networking.
- Use authorized, isolated local environments and synthetic data only. Do not connect personal information, operational accounts, external services, or third-party systems. Do not expose the lab through the internet or a reverse proxy.
- Independently establish and validate isolation before running untrusted attack tools.
- UDP events can be lost; hash chains cannot prevent complete rewriting or deletion. Ordinary hash PoW is parallelizable and is not user authentication.
- Complex deception can introduce maintenance costs and new vulnerabilities. Operational safety, availability, and legitimate-user impact remain unvalidated.

[Detailed limitations and evidence needed](docs/REFERENCE.en.md#unverified-claims-and-why)

## Invitation

**This project is shared for inspiration and open research. Critical feedback, reproducible experiments, and alternative approaches are welcome.**

Share the code revision, environment, comparison conditions, reproduction steps, raw results, and limitations in an
[Issue](https://github.com/daning1212/ARTA-MATRYOSHKA/issues) or Pull Request.
Unexpected outcomes and failed reproductions are useful contributions.

## Technical documentation

The existing research reports are in Korean.

- [Technical reference, examples, and previous README content](docs/REFERENCE.en.md) · [한국어 reference](docs/REFERENCE.ko.md)
- [Design and AI evaluation plan](docs/DESIGN.md) · [Development report](docs/REPORT.md) · [Idea review](docs/IDEA-REVIEW.md)
- [Fixed-script exploration experiment](docs/TIMEATTACK-REPORT.md)
- [PoW pilot](docs/TOLLBENCH-REPORT.md) · [Distinct synthetic collection](docs/COLLECTIONBENCH-REPORT.md)
- [Matched round-trip controls](docs/CONTROLBENCH-REPORT.md) · [Rate-limit and error remeasurement](docs/RATELIMIT-REPORT.md)

Co-developed by **Healing Arty & Arta** · [MIT License](LICENSE)

