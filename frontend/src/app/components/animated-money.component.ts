import { Component, Input, OnChanges, OnDestroy, SimpleChanges, signal } from '@angular/core';

import { formatCOP } from '../core/format';

/** Anima el conteo de un valor numerico y lo formatea como COP. */
@Component({
  selector: 'app-animated-money',
  standalone: true,
  template: `<span>{{ display() }}</span>`,
})
export class AnimatedMoneyComponent implements OnChanges, OnDestroy {
  @Input({ required: true }) value = 0;
  @Input() duration = 850;
  @Input() prefix = '';

  private raf = 0;
  private current = 0;
  readonly display = signal('$0');

  ngOnChanges(changes: SimpleChanges): void {
    if ('value' in changes) this.animate(this.value);
  }

  ngOnDestroy(): void {
    cancelAnimationFrame(this.raf);
  }

  private animate(to: number): void {
    cancelAnimationFrame(this.raf);
    const from = this.current;
    const start = performance.now();
    const dur = this.duration;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);

    const step = (now: number) => {
      const p = Math.min((now - start) / dur, 1);
      this.current = from + (to - from) * ease(p);
      this.display.set(this.prefix + formatCOP(Math.round(this.current)));
      if (p < 1) this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }
}
