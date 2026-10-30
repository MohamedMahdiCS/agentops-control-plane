import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import {
  Activity,
  ArrowRight,
  Boxes,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Gauge,
  GitBranch,
  Hexagon,
  Lock,
  Repeat2,
  ScrollText,
  ShieldCheck,
  Terminal,
  UserCheck,
  Workflow,
} from 'lucide-react'
import overviewShot from './assets/overview.webp'
import regressionShot from './assets/evaluation-regression.webp'
import benchmarksShot from './assets/benchmarks.webp'
import tracesShot from './assets/traces.webp'

const HeroScene = lazy(() => import('./HeroScene'))

const REPO = 'https://github.com/MohamedMahdiCS/agentops-control-plane'

function useReveal() {
  useEffect(() => {
    const items = document.querySelectorAll('.lp-reveal')
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      items.forEach((item) => item.classList.add('is-visible'))
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        }
      },
      { rootMargin: '0px 0px -10% 0px' },
    )
    items.forEach((item) => observer.observe(item))
    return () => observer.disconnect()
  }, [])
}

function Section({
  id,
  eyebrow,
  title,
  lead,
  children,
}: {
  id: string
  eyebrow: string
  title: ReactNode
  lead?: string
  children: ReactNode
}) {
  return (
    <section id={id} className="lp-section" aria-labelledby={`${id}-title`}>
      <div className="lp-section-head lp-reveal">
        <span className="lp-eyebrow">{eyebrow}</span>
        <h2 id={`${id}-title`}>{title}</h2>
        {lead && <p>{lead}</p>}
      </div>
      {children}
    </section>
  )
}

const FEATURES = [
  {
    icon: <ShieldCheck size={20} />,
    title: 'Policy outside the model',
    body: 'Every tool call passes a backend gateway that validates typed arguments, scopes resources and records a decision before anything runs. Unknown tools are denied by default.',
  },
  {
    icon: <Workflow size={20} />,
    title: 'Crash-safe execution',
    body: 'A PostgreSQL queue with leases, fencing generations and checkpoints. Recovered runs never repeat consequential actions, and unknown outcomes are never counted as success.',
  },
  {
    icon: <UserCheck size={20} />,
    title: 'Human approvals',
    body: 'Sensitive actions pause for an operator. Approvals are bound to one action, expire automatically and cannot be replayed.',
  },
  {
    icon: <ClipboardCheck size={20} />,
    title: 'Evidence-based evaluation',
    body: 'A deterministic grader scores runs 0–100 from recorded spans, decisions and audit events. A safety violation fails the run whatever the score.',
  },
  {
    icon: <Repeat2 size={20} />,
    title: 'Reproducible benchmarks',
    body: 'Scenario suites run through the real system, write checksummed manifests, replay, detect regressions and decide release gates, in CI as well.',
  },
  {
    icon: <ScrollText size={20} />,
    title: 'Full traces',
    body: 'Every span and governance event is persisted and explorable, with raw arguments, responses and payloads deliberately kept out of the API.',
  },
]

const STEPS = [
  { icon: <Terminal size={18} />, title: 'Request', body: 'The agent asks for a tool with typed arguments.' },
  { icon: <Lock size={18} />, title: 'Authorize', body: 'The gateway validates, scopes and records the decision first.' },
  { icon: <Activity size={18} />, title: 'Execute or pause', body: 'Reads run with a deadline; sensitive actions wait for a human.' },
  { icon: <ClipboardCheck size={18} />, title: 'Prove', body: 'The run is graded from its evidence and gated in CI.' },
]

const STACK = ['Python 3.12', 'FastAPI', 'Pydantic', 'SQLAlchemy 2', 'PostgreSQL', 'Alembic', 'React 19', 'TypeScript', 'Three.js', 'Docker', 'GitHub Actions']

export default function Landing() {
  useReveal()

  return (
    <div className="lp">
      <a className="lp-skip" href="#main">
        Skip to content
      </a>
      <header className="lp-nav">
        <a className="lp-brand" href="#top" aria-label="AgentOps Control Plane home">
          <span className="lp-brand-mark" aria-hidden="true">
            <Hexagon size={18} />
          </span>
          AgentOps
        </a>
        <nav aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#evaluation">Evaluation</a>
          <a href="#architecture">Architecture</a>
        </nav>
        <a className="lp-button lp-button-ghost" href={REPO}>
          <GitBranch size={15} aria-hidden="true" /> GitHub
        </a>
      </header>

      <main id="main">
        <section id="top" className="lp-hero" aria-labelledby="hero-title">
          <div className="lp-hero-copy">
            <span className="lp-pill lp-reveal">
              <span className="lp-pill-dot" aria-hidden="true" /> Open source · AI agent reliability
            </span>
            <h1 id="hero-title" className="lp-reveal">
              Agents you can <span>prove.</span>
            </h1>
            <p className="lp-lead lp-reveal">
              AgentOps Control Plane runs AI agents with the guarantees production needs:
              policy enforced outside the model, crash-safe execution, human approvals, full
              traces, and deterministic evaluations that show what an agent actually did.
            </p>
            <div className="lp-actions lp-reveal">
              <a className="lp-button lp-button-primary" href={REPO}>
                View on GitHub <ArrowRight size={16} aria-hidden="true" />
              </a>
              <a className="lp-button lp-button-ghost" href="#how">
                See how it works
              </a>
            </div>
          </div>
          <Suspense fallback={<div className="lp-scene lp-scene-loading" aria-hidden="true" />}>
            <HeroScene />
          </Suspense>
        </section>

        <ul className="lp-proof lp-reveal" aria-label="Project facts">
          <li>
            <strong>233</strong>
            <span>automated tests</span>
          </li>
          <li>
            <strong>5</strong>
            <span>versioned benchmark scenarios</span>
          </li>
          <li>
            <strong>100-pt</strong>
            <span>deterministic rubric</span>
          </li>
          <li>
            <strong>CI</strong>
            <span>gated release decisions</span>
          </li>
        </ul>

        <Section
          id="features"
          eyebrow="Capabilities"
          title={<>Built for the moment an agent touches something real</>}
          lead="Safety and reliability are enforced by the platform, not by asking the model nicely."
        >
          <div className="lp-features">
            {FEATURES.map((feature) => (
              <article key={feature.title} className="lp-card lp-reveal">
                <span className="lp-card-icon" aria-hidden="true">
                  {feature.icon}
                </span>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            ))}
          </div>
        </Section>

        <Section
          id="how"
          eyebrow="How it works"
          title="Every tool call is governed, recorded and graded"
          lead="The same path serves day-to-day runs, evaluations and benchmark suites."
        >
          <ol className="lp-steps">
            {STEPS.map((step, index) => (
              <li key={step.title} className="lp-step lp-reveal" style={{ transitionDelay: `${index * 80}ms` }}>
                <span className="lp-step-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="lp-step-icon" aria-hidden="true">
                  {step.icon}
                </span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </Section>

        <Section
          id="evaluation"
          eyebrow="Evaluation and benchmarks"
          title="Scores you can trace back to evidence"
          lead="Four 25-point criteria built from explicit checks. A diagnosis only earns credit if it can be rebuilt from what the run recorded."
        >
          <div className="lp-showcase">
            <ul className="lp-checklist lp-reveal">
              {[
                'Diagnosis correctness, reproducible from recorded evidence',
                'Evidence and tool usage linked to real spans',
                'Policy compliance with a safety gate a high score cannot override',
                'Execution reliability, where unknown outcomes are never success',
                'Regression comparison across runs, with identical-evidence fingerprints',
                'Release gates for platform safety and agent quality',
              ].map((item) => (
                <li key={item}>
                  <CheckCircle2 size={17} aria-hidden="true" />
                  {item}
                </li>
              ))}
            </ul>
            <figure className="lp-frame lp-reveal">
              <img src={regressionShot} width={2368} height={1800} alt="Evaluation comparison showing a regression from 100 to 55 with per-check changes" loading="lazy" />
            </figure>
          </div>
        </Section>

        <Section
          id="console"
          eyebrow="Operator console"
          title="One place to run, watch and prove your agents"
          lead="Live governance stream, interactive agent map, evaluation reports and benchmark comparisons."
        >
          <figure className="lp-frame lp-frame-hero lp-reveal">
            <img src={overviewShot} width={2880} height={1800} alt="AgentOps console overview with live KPIs, agent constellation and governance stream" loading="lazy" />
          </figure>
          <div className="lp-gallery">
            <figure className="lp-frame lp-reveal">
              <img src={benchmarksShot} width={2368} height={1800} alt="Benchmark release gates and scenario results" loading="lazy" />
              <figcaption>
                <Gauge size={15} aria-hidden="true" /> Benchmarks and release gates
              </figcaption>
            </figure>
            <figure className="lp-frame lp-reveal">
              <img src={tracesShot} width={2368} height={1800} alt="Trace explorer timeline of tool spans and audit events" loading="lazy" />
              <figcaption>
                <Activity size={15} aria-hidden="true" /> Trace explorer
              </figcaption>
            </figure>
          </div>
        </Section>

        <Section
          id="architecture"
          eyebrow="Architecture"
          title="A modular monolith with clear boundaries"
          lead="One FastAPI service, PostgreSQL for all state, and a database-backed worker."
        >
          <div className="lp-arch lp-reveal" role="img" aria-label="Architecture: the console calls the FastAPI API; the worker claims runs from PostgreSQL and executes them through the agent runtime and tool gateway; the grader and benchmark runner read recorded evidence.">
            <div className="lp-arch-row">
              <div className="lp-arch-node is-accent">
                <Boxes size={16} aria-hidden="true" /> Operator console
              </div>
            </div>
            <div className="lp-arch-link" aria-hidden="true" />
            <div className="lp-arch-row">
              <div className="lp-arch-node">FastAPI · operator auth · REST</div>
            </div>
            <div className="lp-arch-link" aria-hidden="true" />
            <div className="lp-arch-row lp-arch-row-wide">
              <div className="lp-arch-node">Durable worker</div>
              <div className="lp-arch-node">Agent runtime</div>
              <div className="lp-arch-node is-accent">Tool gateway</div>
              <div className="lp-arch-node">Human approvals</div>
            </div>
            <div className="lp-arch-link" aria-hidden="true" />
            <div className="lp-arch-row lp-arch-row-wide">
              <div className="lp-arch-node">Deterministic grader</div>
              <div className="lp-arch-node">Benchmark runner</div>
              <div className="lp-arch-node is-cyan">
                <Database size={15} aria-hidden="true" /> PostgreSQL evidence
              </div>
            </div>
          </div>
          <ul className="lp-stack lp-reveal" aria-label="Technology stack">
            {STACK.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Section>

        <section className="lp-cta lp-reveal" aria-labelledby="cta-title">
          <h2 id="cta-title">Explore the code</h2>
          <p>Clone it, run the deterministic suite and replay a benchmark in minutes.</p>
          <pre>
            <code>git clone {REPO}.git</code>
          </pre>
          <a className="lp-button lp-button-primary" href={REPO}>
            View on GitHub <ArrowRight size={16} aria-hidden="true" />
          </a>
        </section>
      </main>

      <footer className="lp-footer">
        <span>
          Built by{' '}
          <a href="https://www.linkedin.com/in/mohamedmahdi-cs/">Mohamed Mahdi</a> · Apache-2.0
        </span>
        <span>
          <a href={REPO}>GitHub</a> · <a href={`${REPO}#readme`}>Documentation</a>
        </span>
      </footer>
    </div>
  )
}
