import { MethodsExplainer } from '../components/methods/MethodsExplainer';
import { Panel } from '../components/ui/Panel';

const LIMITS = [
  'One microphone cannot estimate abundance. Metrics describe detection events, which depend on how loud and how often species call.',
  'BirdNET has not been validated for every region, habitat or recorder. Check uncertain detections by ear before relying on them.',
  'Species outside the expected range or season are flagged, not silently removed, so rare but real records stay visible.',
  'Experimental models are hidden unless explicitly enabled and are always labeled. They are leads, not evidence.',
  'Thicket does not certify regulatory compliance and does not infer causes from detections.',
];

export function MethodsPage() {
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-[1.75rem] font-semibold tracking-tight text-ink">Methods</h1>
        <p className="mt-2 text-base text-muted">
          How Thicket turns a recording into detection events and metrics, and what those numbers
          can and cannot tell you. Each analysis records the exact settings it used on its Methods
          tab.
        </p>
      </div>
      <div className="grid gap-6 lg:grid-cols-12">
        <Panel labelledBy="pipeline-heading" className="p-5 sm:p-7 lg:col-span-7">
          <h2 id="pipeline-heading" className="text-base font-semibold tracking-tight text-ink">
            From audio to evidence
          </h2>
          <MethodsExplainer className="mt-5" />
        </Panel>
        <div className="space-y-6 lg:col-span-5">
          <Panel labelledBy="limits-heading" className="p-5 sm:p-7">
            <h2 id="limits-heading" className="text-base font-semibold tracking-tight text-ink">
              Limits to keep in mind
            </h2>
            <ul className="mt-4 space-y-3 text-sm leading-relaxed text-muted">
              {LIMITS.map((item) => (
                <li key={item} className="border-l-2 border-mark/40 pl-3">
                  {item}
                </li>
              ))}
            </ul>
          </Panel>
          <Panel labelledBy="privacy-heading" className="p-5 sm:p-7">
            <h2 id="privacy-heading" className="text-base font-semibold tracking-tight text-ink">
              Privacy
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              Audio is processed on your own Thicket server and is not kept after analysis unless
              retention is turned on. When the model hears human speech, the results say so, and you
              can delete an analysis with all derived files at any time. Your browser keeps only
              short summaries of the last three analyses.
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
