/**
 * ROI Formatting Helpers
 *
 * Provides Intl.NumberFormat currency formatters for Indian Grouping INR (₹)
 * and Standard Grouping USD ($).
 */

/**
 * Formats a value into local currency representation.
 */
export function formatCurrency(
  value: number,
  currency: "INR" | "USD" = "INR",
  isCompact = false
): string {
  if (currency === "USD") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: isCompact && value >= 1000 ? 1 : 0,
      notation: isCompact ? "compact" : "standard",
    }).format(value);
  }

  // Indian Rupees INR Formatting (using Grouping 2,2,3 - e.g. 12,50,000)
  if (isCompact) {
    if (value >= 10000000) {
      // Crores
      return `₹${(value / 10000000).toFixed(1)} Cr`;
    }
    if (value >= 100000) {
      // Lakhs
      return `₹${(value / 100000).toFixed(1)}L`;
    }
    if (value >= 1000) {
      // Thousands
      return `₹${(value / 1000).toFixed(1)}K`;
    }
    return `₹${value}`;
  }

  // standard formatting with en-IN locale
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}
