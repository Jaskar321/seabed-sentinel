"""
Unsupervised models for Seabed Sentinel, split so it works at MANY spots.

  BehaviorModel  - GLOBAL / portable. Trained once on pooled tracks from several
                   spots+days, on PLACE-INDEPENDENT motion features. Answers
                   "does this vessel move oddly?" and transfers to any waterway.

  RouteModel     - PER-SPOT. A self-calibrating lane-density grid for one
                   waterway. Built from that spot's own history (or learned live).
                   Answers "is this vessel off the normal lanes HERE?"

The physics rules in seabed.py stay the global, interpretable threat layer.
Sabotage is far too rare to train a supervised classifier - this models NORMAL
and scores deviation.
"""
import numpy as np
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Place-INDEPENDENT motion features -> pooled training transfers across spots.
# (No min_cable_km / lat / lon here - those are location-relative.)
BEHAVIOR_FEATURES = ["sog_median", "moving_speed_med", "straightness",
                     "slow_moving_km", "cog_std", "hdg_cog_mismatch", "max_gap_min"]


class BehaviorModel:
    """Global, portable behavioural-anomaly model."""
    def __init__(self):
        self.scaler = None
        self.iforest = None
        self._smin, self._smax = 0.0, 1.0

    def fit(self, feats_list):
        X = np.nan_to_num(np.array([[f.get(k, 0.0) for k in BEHAVIOR_FEATURES]
                                    for f in feats_list], float))
        self.scaler = StandardScaler().fit(X)
        self.iforest = IsolationForest(n_estimators=300, contamination="auto",
                                       random_state=0).fit(self.scaler.transform(X))
        s = -self.iforest.score_samples(self.scaler.transform(X))
        self._smin, self._smax = float(s.min()), float(s.max())
        return self

    def anomaly(self, f):
        x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in BEHAVIOR_FEATURES]], float))
        s = -self.iforest.score_samples(self.scaler.transform(x))[0]
        return float(np.clip((s - self._smin) / ((self._smax - self._smin) or 1.0), 0.0, 1.0))

    def save(self, path="behavior_model.joblib"):
        joblib.dump(self, path)

    @staticmethod
    def load(path="behavior_model.joblib"):
        return joblib.load(path)


class RouteModel:
    """Per-spot lane-density model. Self-calibrating: fit on history, or update() live."""
    def __init__(self, bbox, cell=0.005):
        self.bbox = bbox            # (lat_min, lat_max, lon_min, lon_max)
        self.cell = cell
        self.grid = None
        self.shape = None
        self.thresh = 0.0

    def _mk(self):
        la0, la1, lo0, lo1 = self.bbox
        nr = int((la1 - la0) / self.cell) + 1
        nc = int((lo1 - lo0) / self.cell) + 1
        self.grid = np.zeros((nr, nc)); self.shape = (nr, nc)

    def _idx(self, lat, lon):
        la0, _, lo0, _ = self.bbox
        return int((lat - la0) / self.cell), int((lon - lo0) / self.cell)

    def update(self, coords):
        """Accumulate traffic density (use to self-calibrate offline or live)."""
        if self.grid is None:
            self._mk()
        nr, nc = self.shape
        for lat, lon in coords:
            r, c = self._idx(lat, lon)
            if 0 <= r < nr and 0 <= c < nc:
                self.grid[r, c] += 1

    def finalize(self):
        occ = self.grid[self.grid > 0]
        self.thresh = float(np.percentile(occ, 20)) if len(occ) else 0.0

    def fit(self, coords_list):
        self._mk()
        for coords in coords_list:
            self.update(coords)
        self.finalize()
        return self

    def anomaly(self, coords):
        if self.grid is None or not coords:
            return 0.0
        nr, nc = self.shape
        low = tot = 0
        for lat, lon in coords:
            r, c = self._idx(lat, lon)
            if 0 <= r < nr and 0 <= c < nc:
                tot += 1
                if self.grid[r, c] <= self.thresh:
                    low += 1
        return low / tot if tot else 0.0

    def save(self, path):
        joblib.dump(self, path)

    @staticmethod
    def load(path):
        return joblib.load(path)
