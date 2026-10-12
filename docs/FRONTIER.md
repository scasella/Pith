# Where the frontier is (October 2026), and what this template takes from it

Compiled from a search on 2026-10-11; links are to the sources read.

**The practice has a name.** Generating formally verified code from a formal specification
is now called *vericoding*, in contrast to vibe coding. The largest benchmark (Beneficial AI
Foundation et al.; Dafny 2026 workshop at POPL; TMLR under review) holds 12,504 formal
specifications across Dafny, Verus/Rust, and Lean. Off-the-shelf LLM success: ~82% Dafny,
~44% Verus, ~27% Lean; pure Dafny verification success rose from 68% to 97% in a year.
Adding natural-language descriptions to the formal spec did not significantly help.
— https://arxiv.org/pdf/2509.22908 ; https://popl26.sigplan.org/details/dafny-2026-papers/13/

*Taken:* Dafny as the template language; the template carries no prose beyond a glossary.

**Repository scale is the open problem.** Vero (Aug 2026) benchmarks agents building
formally verified multi-module repositories in Lean 4 from real-world sources; current
agents "still fall short". VeriSoftBench is repository-scale but proof-only. Vero also adds an
*audit mechanism*: agents may formally prove a provided specification unsatisfiable, which
surfaced latent specification errors during curation.
— https://arxiv.org/pdf/2608.13522

*Taken:* the `audit/` channel; the template's scope is one bounded core, not a repository.

**Specification gaming is the central failure mode.** AlgoVeri (2026) separates verified
from "full mark" results using a semantic validator, reporting two failure classes: cheating
(`assume` of a contradiction, `sorry`, bypass attributes) and algorithmic degeneracy
(verifying a simpler problem than asked). The vericoding benchmark ships a block-validation
script for cheating patterns and documents an LLM exploiting an incomplete spec. Verus-SpecGym
finds execution-based checking catches spec errors LLM-as-judge misses. VeriAct reports that
verifier-accepted Dafny specs are often semantically wrong. Clover (earlier) framed this as
needing a consistency check across code, annotations, and intent. The `fsl` toolchain builds
vacuity checks (unreachable antecedent, always-true requires) into its gate.
— https://arxiv.org/html/2602.09464v2 ; https://arxiv.org/pdf/2605.26457 ;
  https://arxiv.org/pdf/2607.09900 ; https://github.com/ymm-oss/fsl/issues/1103

*Taken:* the TCB scan (`kernel/tcb.yaml`), warnings-as-errors, the adequacy suite of wrong
candidates with expected rejecting obligations, and executable traces as the
specification-adequacy check. The template treats "verifier accepted" as necessary, not
sufficient.

**Agentic verification toolchains are productizing.** AxDafny, DafnyPro (Banerjee,
Bouissou, Zetzsche, 2026), WybeCoder, and SkillForge report agentic Dafny/Lean pipelines
with verification-in-the-loop; AutoVerus for Rust. Pramaana Labs raised a seed round
(June 2026) for formal verification of AI-written code in high-stakes verticals.
— https://arxiv.org/pdf/2606.32007 ; https://arxiv.org/pdf/2603.29088 ;
  https://arxiv.org/pdf/2608.29841 ; https://bwetzel.medium.com/vericoding-formal-verification-for-ai-code-generation-06f043bc660f

*Taken:* nothing specific; the gate is tool-agnostic and would sit after any of these.

**Spec-driven tools already extract properties.** Kiro extracts properties from EARS
requirements and runs property-based tests, calling the result evidence rather than proof.
— https://kiro.dev/docs/specs/correctness/

*Taken:* the template is positioned as the formal core inside that workflow, not a
replacement for it.

## What the frontier does not yet give you

- A way to validate a formal template against intent without humans. Every source above
  that measured it found verifier-accepted specs that were wrong; the fixes are external
  (tests, traces, judges, wrong candidates). This template ships those as artifacts and
  still needs a human to sign them.
- Repository-scale synthesis against a formal template. The benchmarks that try it report
  agents falling short; the honest unit today is a module with a handful of obligations.
- Proofs that cross into databases, frameworks and networks *in this package*. That is a scope
  choice here, not a limit of the field: IronFleet, Verdi and successors verify distributed systems
  at the implementation level. The seed's `not_covered` list says what this package does not
  supply, and alternative integration profiles are the place to supply more.
