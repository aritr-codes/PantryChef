// A small undo bar. The container is always in the page and is a polite live region, so a screen
// reader announces the message when it appears. It never takes focus.

export interface Undo {
  where: "kitchen" | "ticket";
  msg: string;
  run: () => void;
}

export function UndoBar(p: { where: Undo["where"]; undo: Undo | null; onDone: () => void }) {
  const mine = p.undo?.where === p.where ? p.undo : null;
  return (
    <div class="undo" role="status" aria-live="polite">
      {mine && (
        <>
          <span>{mine.msg}</span>
          <button
            type="button"
            onClick={() => {
              mine.run();
              p.onDone();
            }}
          >
            Undo
          </button>
        </>
      )}
    </div>
  );
}
