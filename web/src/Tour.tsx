import { useLayoutEffect, useState } from "react";

export type TourStep = {
  id: string;
  title: string;
  body: string;
};

type Box = { top: number; left: number; width: number; height: number };

export default function Tour({
  steps,
  index,
  onIndex,
  onDone,
}: {
  steps: TourStep[];
  index: number;
  onIndex: (n: number) => void;
  onDone: () => void;
}) {
  const step = steps[index];
  const [box, setBox] = useState<Box | null>(null);
  const last = index >= steps.length - 1;

  useLayoutEffect(() => {
    function measure() {
      const el = document.querySelector(`[data-tour="${step.id}"]`);
      if (!el) {
        setBox(null);
        return;
      }
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    }
    measure();
    const t = window.setTimeout(measure, 60);
    const t2 = window.setTimeout(measure, 220);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearTimeout(t);
      window.clearTimeout(t2);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step.id, index]);

  useLayoutEffect(() => {
    function keys(e: KeyboardEvent) {
      if (e.key === "Escape") onDone();
      if (e.key === "ArrowRight" || e.key === "Enter") {
        e.preventDefault();
        last ? onDone() : onIndex(index + 1);
      }
      if (e.key === "ArrowLeft" && index > 0) {
        e.preventDefault();
        onIndex(index - 1);
      }
    }
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [index, last, onDone, onIndex]);

  const pad = 10;
  const hole = box
    ? {
        top: Math.max(8, box.top - pad),
        left: Math.max(8, box.left - pad),
        width: Math.min(window.innerWidth - 16, box.width + pad * 2),
        height: Math.min(window.innerHeight - 16, box.height + pad * 2),
      }
    : null;
  const bottom = hole ? hole.top + hole.height : 0;
  const tipAbove = hole ? bottom > window.innerHeight - 230 : false;
  const tipTop = hole
    ? tipAbove
      ? Math.max(16, hole.top - 200)
      : Math.min(window.innerHeight - 210, bottom + 14)
    : Math.max(24, window.innerHeight / 2 - 120);
  const tipLeft = hole ? Math.min(Math.max(16, hole.left), window.innerWidth - 392) : 24;

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title">
      {hole ? (
        <>
          <div className="tour-blur" style={{ top: 0, left: 0, right: 0, height: hole.top }} />
          <div className="tour-blur" style={{ top: hole.top, left: 0, width: hole.left, height: hole.height }} />
          <div
            className="tour-blur"
            style={{ top: hole.top, left: hole.left + hole.width, right: 0, height: hole.height }}
          />
          <div className="tour-blur" style={{ top: hole.top + hole.height, left: 0, right: 0, bottom: 0 }} />
          <div className="tour-hole" style={{ top: hole.top, left: hole.left, width: hole.width, height: hole.height }} />
        </>
      ) : (
        <div className="tour-blur" style={{ inset: 0 }} />
      )}

      <div className="tour-tip" style={{ top: tipTop, left: tipLeft }}>
        <div className="kicker">
          {index + 1} / {steps.length}
        </div>
        <h2 id="tour-title" className="display text-[22px] mt-1 leading-tight">
          {step.title}
        </h2>
        <p className="text-[13.5px] font-light leading-relaxed mt-2 text-[var(--ink)]/85">{step.body}</p>
        <div className="mt-4 flex items-center gap-2">
          <button type="button" className="text-[12px] text-[var(--muted)] px-2 py-1" onClick={onDone}>
            Skip
          </button>
          <div className="ml-auto flex gap-2">
            {index > 0 && (
              <button
                type="button"
                className="text-[12px] px-3 py-1.5 rounded-full glass-c"
                onClick={() => onIndex(index - 1)}
              >
                Back
              </button>
            )}
            <button
              type="button"
              className="text-[12px] px-4 py-1.5 rounded-full glass-active"
              onClick={() => (last ? onDone() : onIndex(index + 1))}
            >
              {last ? "Start using Ikigai" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
