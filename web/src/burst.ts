// A small burst of coloured dots on an element. It is decoration, it never takes focus, and it
// does nothing when the system asks for reduced motion. The dots are removed after 800 ms.
// Position and direction go in through the CSS object model, which the page policy allows.

const COLOURS = 4; // c0 to c3 in style.css
const DOTS = 12;

export function burst(el: HTMLElement | null): void {
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!el || reduce) return;
  for (let i = 0; i < DOTS; i++) {
    const angle = (i / DOTS) * Math.PI * 2;
    const dist = 34 + (i % 3) * 12;
    const dot = document.createElement("span");
    dot.className = `dot c${i % COLOURS}`;
    dot.setAttribute("aria-hidden", "true");
    dot.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
    dot.style.setProperty("--dy", `${Math.sin(angle) * dist}px`);
    el.appendChild(dot);
    setTimeout(() => dot.remove(), 800);
  }
}
