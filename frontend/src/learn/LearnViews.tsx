import { useMemo, useState } from "react";

import type { LearnProgress } from "../types";
import { GLOSSARY, LESSONS, MODULES, findLesson } from "./course";
import { renderMarkdown } from "./markdown";

export function lessonsDone(progress: LearnProgress): number {
  return LESSONS.filter((lesson) => progress.lessons[lesson.id]).length;
}

export function LearnPanel({ progress }: { progress: LearnProgress }) {
  const done = lessonsDone(progress);
  const next = LESSONS.find((lesson) => !progress.lessons[lesson.id]);
  return (
    <section className="panel learn-panel" aria-labelledby="learn-panel-title">
      <h2 id="learn-panel-title">Learn</h2>
      <p className="muted small">
        {done} of {LESSONS.length} lessons done.
      </p>
      <div
        className="meter-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={LESSONS.length}
        aria-valuenow={done}
        aria-label="Lessons done"
      >
        <div className="meter-fill" style={{ width: `${(done / LESSONS.length) * 100}%` }} />
      </div>
      {next ? (
        <p className="next-lesson">
          Next: <a href={`#/learn/${next.id}`}>{next.title}</a> <span className="muted small">{next.minutes} min</span>
        </p>
      ) : (
        <p className="next-lesson">Every lesson is done. The quizzes are a good review.</p>
      )}
      <p className="small learn-links">
        <a href="#/learn">All lessons and quizzes</a>
        <a href="#/learn/glossary">Glossary</a>
      </p>
    </section>
  );
}

export function LearnHome({ progress }: { progress: LearnProgress }) {
  const done = lessonsDone(progress);
  return (
    <div className="learn">
      <header className="learn-head">
        <h1>Learn</h1>
        <p className="lead">
          Short lessons on how this app trades and why: orders, risk, the two strategies, how to test them before real
          money, crypto and forex. Written for beginners, about {Math.round(LESSONS.reduce((sum, l) => sum + l.minutes, 0) / 5) * 5}{" "}
          minutes in all.
        </p>
        <p className="muted small">
          {done} of {LESSONS.length} lessons done. <a href="#/learn/glossary">Glossary</a>
        </p>
      </header>
      <ol className="modules">
        {MODULES.map((module) => {
          const quiz = progress.quizzes[module.id];
          return (
            <li key={module.id} className="module">
              <h2>{module.title}</h2>
              <p className="muted">{module.summary}</p>
              <ul className="lesson-list">
                {module.lessons.map((lesson) => {
                  const finished = Boolean(progress.lessons[lesson.id]);
                  return (
                    <li key={lesson.id} className={finished ? "done" : ""}>
                      <a href={`#/learn/${lesson.id}`}>{lesson.title}</a>
                      <span className="muted small">{lesson.minutes} min</span>
                      {finished && <span className="done-mark">Done</span>}
                    </li>
                  );
                })}
                <li className="quiz-row">
                  <a href={`#/learn/quiz/${module.id}`}>Quiz: {module.quiz.length} questions</a>
                  {quiz && (
                    <span className="muted small">
                      Best {quiz.best} of {quiz.total}
                    </span>
                  )}
                </li>
              </ul>
            </li>
          );
        })}
      </ol>
      <p className="muted small learn-foot">
        These lessons teach how the app works; they aren't investment, tax or legal advice.
      </p>
    </div>
  );
}

export function LessonView({
  id,
  progress,
  onMark,
}: {
  id: string;
  progress: LearnProgress;
  onMark: (id: string, done: boolean) => Promise<void>;
}) {
  const found = findLesson(id);
  const html = useMemo(() => (found ? renderMarkdown(found.lesson.body) : ""), [found]);
  const [saving, setSaving] = useState(false);
  if (!found) return <Missing what="lesson" />;

  const { lesson, module, index } = found;
  const finished = Boolean(progress.lessons[lesson.id]);
  const previous = index > 0 ? LESSONS[index - 1] : null;
  const next = index < LESSONS.length - 1 ? LESSONS[index + 1] : null;
  const lastInModule = module.lessons[module.lessons.length - 1].id === lesson.id;

  async function toggle() {
    setSaving(true);
    try {
      await onMark(lesson.id, !finished);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="learn">
      <nav className="crumbs small" aria-label="Breadcrumb">
        <a href="#/learn">Learn</a> <span aria-hidden="true">/</span> {module.title}
        <span className="muted"> {lesson.minutes} min read</span>
      </nav>
      <article className="lesson" dangerouslySetInnerHTML={{ __html: html }} />
      <div className="lesson-foot">
        <button type="button" className={finished ? "btn btn-quiet" : "btn btn-go"} disabled={saving} onClick={() => void toggle()}>
          {finished ? "Mark as not done" : "Mark as done"}
        </button>
        {finished && <span className="done-mark">Done</span>}
      </div>
      <nav className="pager" aria-label="Lessons">
        {previous ? (
          <a href={`#/learn/${previous.id}`} className="pager-prev">
            <span className="muted small">Previous</span>
            {previous.title}
          </a>
        ) : (
          <span />
        )}
        {lastInModule ? (
          <a href={`#/learn/quiz/${module.id}`} className="pager-next">
            <span className="muted small">Check yourself</span>
            {module.title} quiz
          </a>
        ) : next ? (
          <a href={`#/learn/${next.id}`} className="pager-next">
            <span className="muted small">Next</span>
            {next.title}
          </a>
        ) : null}
      </nav>
    </div>
  );
}

export function QuizView({
  id,
  progress,
  onQuiz,
}: {
  id: string;
  progress: LearnProgress;
  onQuiz: (moduleId: string, score: number, total: number) => Promise<void>;
}) {
  const module = MODULES.find((m) => m.id === id);
  const [answers, setAnswers] = useState<(number | null)[]>(() => (module ? module.quiz.map(() => null) : []));
  const [checked, setChecked] = useState(false);
  if (!module) return <Missing what="quiz" />;

  const score = module.quiz.reduce((sum, q, i) => sum + (answers[i] === q.answer ? 1 : 0), 0);
  const complete = answers.every((a) => a !== null);
  const position = MODULES.findIndex((m) => m.id === module.id);
  const nextModule = MODULES[position + 1];
  const best = progress.quizzes[module.id]?.best;

  async function check() {
    setChecked(true);
    await onQuiz(module!.id, score, module!.quiz.length);
  }

  function retry() {
    setAnswers(module!.quiz.map(() => null));
    setChecked(false);
    window.scrollTo(0, 0);
  }

  return (
    <div className="learn">
      <nav className="crumbs small" aria-label="Breadcrumb">
        <a href="#/learn">Learn</a> <span aria-hidden="true">/</span> {module.title}
      </nav>
      <h1>{module.title} quiz</h1>
      <p className="lead">
        {module.quiz.length} questions. Pick an answer for each, then check them.
        {best != null && ` Your best so far: ${best} of ${module.quiz.length}.`}
      </p>
      <ol className="quiz">
        {module.quiz.map((question, qi) => {
          const chosen = answers[qi];
          const right = chosen === question.answer;
          return (
            <li key={question.prompt} className={checked ? (right ? "quiz-right" : "quiz-wrong") : ""}>
              <fieldset disabled={checked}>
                <legend>{question.prompt}</legend>
                {question.options.map((option, oi) => (
                  <label
                    key={option}
                    className={
                      checked && oi === question.answer ? "answer" : checked && chosen === oi ? "picked-wrong" : undefined
                    }
                  >
                    <input
                      type="radio"
                      name={`${module.id}-${qi}`}
                      checked={chosen === oi}
                      onChange={() => setAnswers((current) => current.map((a, i) => (i === qi ? oi : a)))}
                    />
                    {option}
                  </label>
                ))}
              </fieldset>
              {checked && (
                <p className="explain">
                  <strong>{right ? "Right." : "Not quite."}</strong> {question.explain}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      {checked ? (
        <div className="quiz-result" role="status">
          <p className="figure">
            {score} of {module.quiz.length}
          </p>
          <p>
            {score === module.quiz.length
              ? "Every answer right."
              : "Read the explanations above, then try again whenever you like."}
          </p>
          <div className="quiz-actions">
            <button type="button" className="btn btn-quiet" onClick={retry}>
              Try again
            </button>
            {nextModule ? (
              <a className="btn btn-go" href={`#/learn/${nextModule.lessons[0].id}`}>
                Next: {nextModule.title}
              </a>
            ) : (
              <a className="btn btn-go" href="#/learn">
                Back to Learn
              </a>
            )}
          </div>
        </div>
      ) : (
        <button type="button" className="btn btn-go" disabled={!complete} onClick={() => void check()}>
          Check answers
        </button>
      )}
    </div>
  );
}

export function GlossaryView() {
  const entries = Object.entries(GLOSSARY).sort(([, a], [, b]) => a.term.localeCompare(b.term));
  const titles = new Map(LESSONS.map((lesson) => [lesson.id, lesson.title]));
  return (
    <div className="learn">
      <nav className="crumbs small" aria-label="Breadcrumb">
        <a href="#/learn">Learn</a> <span aria-hidden="true">/</span> Glossary
      </nav>
      <h1>Glossary</h1>
      <p className="lead">The words the app uses, in plain language. Tap a dotted word on the dashboard to see one.</p>
      <dl className="glossary">
        {entries.map(([key, entry]) => (
          <div key={key} id={`term-${key}`}>
            <dt>{entry.term}</dt>
            <dd>
              {entry.definition}{" "}
              {entry.lesson && (
                <a href={`#/learn/${entry.lesson}`} className="small">
                  {titles.get(entry.lesson)}
                </a>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Missing({ what }: { what: string }) {
  return (
    <div className="learn">
      <h1>That {what} isn't here</h1>
      <p>
        It may have been renamed. <a href="#/learn">See every lesson</a>.
      </p>
    </div>
  );
}
