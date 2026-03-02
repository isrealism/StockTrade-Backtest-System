import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(num: number, decimals = 2): string {
  if (Math.abs(num) >= 1e8) {
    return (num / 1e8).toFixed(decimals) + "亿";
  }
  if (Math.abs(num) >= 1e4) {
    return (num / 1e4).toFixed(decimals) + "万";
  }
  return num.toFixed(decimals);
}

export function formatPercent(num: number, decimals = 2): string {
  return num.toFixed(decimals) + "%";
}

export function formatDate(date: string): string {
  if (!date) return "-";
  return date.split("T")[0];
}
