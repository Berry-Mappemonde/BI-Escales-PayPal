/**
 * Where the boat is, in words a visitor can read: waiting before departure,
 * stopped at a stop, or under way between two stops.
 *
 * `stops` are the voyage stops in route order, each with its distance along the
 * route (`filmNm`, or `nm`); `sample` is the clock sample for "now".
 */
const distanceOf = (point) => {
  const film = Number(point?.filmNm);
  if (Number.isFinite(film)) return film;
  const nm = Number(point?.nm);
  return Number.isFinite(nm) ? nm : null;
};

export function boatPosition(stops, sample) {
  const list = (stops || []).filter((stop) => stop?.name && distanceOf(stop) !== null);
  if (!sample || !list.length) return null;
  const here = distanceOf(sample);
  if (here === null) return null;

  // The last stop already reached and the first one still ahead.
  let behind = null;
  let ahead = null;
  for (const stop of list) {
    if (distanceOf(stop) <= here + 0.45) behind = stop;
    else if (!ahead) ahead = stop;
  }

  if (sample.status === "waiting") return { kind: "waiting", stop: (behind ?? list[0]).name };
  if (sample.status === "arrived" || !ahead) return { kind: "stop", stop: (behind ?? list[list.length - 1]).name };
  if (sample.atQuay && behind) return { kind: "stop", stop: behind.name };
  if (!behind) return { kind: "waiting", stop: list[0].name };
  return { kind: "underway", from: behind.name, to: ahead.name };
}
