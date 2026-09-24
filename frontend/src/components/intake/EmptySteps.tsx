const STEPS = [
  {
    title: 'Choose a recording',
    body: 'A WAV, MP3, M4A or FLAC file up to 20 MB. A few minutes of dawn chorus or evening calls works well.',
  },
  {
    title: 'Add location and date if known',
    body: 'They let BirdNET flag species that are unlikely for the place and season. Leave them blank if unsure; nothing is guessed.',
  },
  {
    title: 'Run the analysis',
    body: 'Follow each stage as it runs, then review species, detection events, metrics and exports.',
  },
];

export function EmptySteps() {
  return (
    <section aria-labelledby="how-heading" className="mx-auto max-w-5xl pt-4">
      <h2 id="how-heading" className="eyebrow mb-5 text-center">
        How it works
      </h2>
      <ol className="grid gap-6 sm:grid-cols-3 sm:gap-8">
        {STEPS.map((step, index) => (
          <li key={step.title} className="border-t border-line-strong pt-4">
            <span className="num text-sm font-semibold text-accent" aria-hidden="true">
              0{index + 1}
            </span>
            <h3 className="mt-1 text-sm font-semibold text-ink">{step.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
