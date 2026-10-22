import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** shadcn's cn(): merge conditional classes, later wins. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
