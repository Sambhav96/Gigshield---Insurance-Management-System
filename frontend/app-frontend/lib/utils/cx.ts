/**
 * A tiny utility safely merging typical class arrays.
 * Bypassing 'tailwind-merge' requirement since we are strictly isolating components
 * and NOT utilizing complex generic overlays. 
 */
export function cx(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}
