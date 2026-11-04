/**
 * Boat speed from the raw TWA×TWS table (bilinear).
 * Same rule as PolarData.speed on the server — not the 181×61 grid.
 * TWA/TWS → polarSpeed idea (signalk-polar-performance), original code.
 */

function bracket(val, arr) {
  if (!arr.length) return [0, 0];
  if (val <= arr[0]) return [0, 0];
  const last = arr.length - 1;
  if (val >= arr[last]) return [last, last];
  for (let i = 0; i < last; i++) {
    if (val <= arr[i + 1]) return [i, i + 1];
  }
  return [last, last];
}

export function hasPolarRaw(raw) {
  return Boolean(
    raw
    && Array.isArray(raw.twa_rows) && raw.twa_rows.length
    && Array.isArray(raw.tws_cols) && raw.tws_cols.length
    && Array.isArray(raw.matrix) && raw.matrix.length,
  );
}

/**
 * @returns {number|null} knots, or null if there is no table
 */
export function polarBoatSpeed(raw, twa, tws) {
  if (!hasPolarRaw(raw)) return null;
  const rows = raw.twa_rows.map(Number);
  const cols = raw.tws_cols.map(Number);
  let a = Math.abs(Number(twa));
  const w = Number(tws);
  if (!Number.isFinite(a) || !Number.isFinite(w)) return null;
  if (w <= 0 || a <= 0) return 0;
  a = Math.min(180, a);
  const twaMin = rows[0];
  const twsMax = cols[cols.length - 1];
  const effW = Math.min(w, twsMax);

  const bilinear = (ta, tw) => {
    const [i0, i1] = bracket(ta, rows);
    const [j0, j1] = bracket(tw, cols);
    const v00 = Number(raw.matrix[i0]?.[j0]);
    const v10 = Number(raw.matrix[i1]?.[j0]);
    const v01 = Number(raw.matrix[i0]?.[j1]);
    const v11 = Number(raw.matrix[i1]?.[j1]);
    if (![v00, v10, v01, v11].every(Number.isFinite)) return 0;
    const tSpan = (rows[i1] - rows[i0]) || 1;
    const wSpan = (cols[j1] - cols[j0]) || 1;
    const ft = i0 === i1 ? 0 : (ta - rows[i0]) / tSpan;
    const fw = j0 === j1 ? 0 : (tw - cols[j0]) / wSpan;
    return v00 * (1 - ft) * (1 - fw)
      + v10 * ft * (1 - fw)
      + v01 * (1 - ft) * fw
      + v11 * ft * fw;
  };

  if (a < twaMin) {
    return Math.round(bilinear(twaMin, effW) * (a / twaMin) * 1000) / 1000;
  }
  if (a > rows[rows.length - 1]) a = rows[rows.length - 1];
  return Math.round(bilinear(a, effW) * 1000) / 1000;
}
