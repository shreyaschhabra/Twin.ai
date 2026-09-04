"""Materialize the frozen pre-ML causal datasets; no model fitting occurs here."""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import UTC, datetime
from pathlib import Path
import numpy as np
import pandas as pd
try:
    from .validate_causal_dataset_contract import (
        DEFECT_FEATURES,
        BOTTLENECK_FEATURES,
        REQUIRED_SENSOR_SIGNALS,
        build_report as slow_build_report,
    )
    from .causal_validation import validate
except ImportError:  # Direct script execution: python training/build_causal_datasets.py
    from validate_causal_dataset_contract import (
        DEFECT_FEATURES,
        BOTTLENECK_FEATURES,
        REQUIRED_SENSOR_SIGNALS,
        build_report as slow_build_report,
    )
    from causal_validation import validate

SCHEMA_VERSION = "causal-features-v1"; RECENT_MS = 600_000; HORIZON_MS = 1_800_000

REQUIRED_RAW_FILES = {
    "station_events.csv", "sensor_readings.csv", "manual_checks.csv",
    "inspection_results.csv", "stations.csv", "units.csv", "run_metadata.json",
}


class TemporalStats:
    """Timestamp index preserving the builder's mean/std/max semantics."""
    def __init__(self, frame, value_column):
        x=frame[["timestamp_ms",value_column]].dropna().sort_values("timestamp_ms",kind="stable")
        self.t=x.timestamp_ms.to_numpy(dtype=np.int64); self.v=x[value_column].to_numpy(dtype=float)
        self.n=len(self.v); self.sum=np.r_[0.,np.cumsum(self.v)]; self.sum2=np.r_[0.,np.cumsum(self.v*self.v)]; self.max=np.r_[-np.inf,np.maximum.accumulate(self.v)]
    def values(self, end, start=None):
        hi=np.searchsorted(self.t,end,side="left")
        lo=0 if start is None else np.searchsorted(self.t,start,side="left")
        n=hi-lo
        if not n: return (np.nan,np.nan,np.nan)
        mean=(self.sum[hi]-self.sum[lo])/n
        std=np.sqrt(max(0.,((self.sum2[hi]-self.sum2[lo])-n*mean*mean)/(n-1))) if n>1 else np.nan
        # Recent maxima retain the exact window aggregate; history uses the causal prefix maximum.
        maximum=self.max[hi] if lo==0 else (self.v[lo:hi].max() if n else np.nan)
        return mean,std,maximum

def station_num(x): return int(str(x).replace("S", ""))
def git(root):
    try: return subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    except Exception: return None
def stat(v):
    v=np.asarray(v,dtype=float); return (np.nanmean(v) if len(v) else np.nan, np.nanstd(v,ddof=1) if len(v)>1 else np.nan, np.nanmax(v) if len(v) else np.nan)
def prefix_stats(values):
    values=np.asarray(values,dtype=float); valid=np.isfinite(values); safe=np.where(valid,values,0.)
    return valid,np.r_[0,np.cumsum(valid)],np.r_[0.,np.cumsum(safe)],np.r_[0.,np.cumsum(safe*safe)]
def range_stats(values,prefix,lo,hi):
    valid,count,total,total2=prefix; n=int(count[hi]-count[lo])
    if not n: return (np.nan,np.nan,np.nan)
    mean=(total[hi]-total[lo])/n; std=np.sqrt(max(0.,((total2[hi]-total2[lo])-n*mean*mean)/(n-1))) if n>1 else np.nan
    return mean,std,float(np.nanmax(values[lo:hi]))
def win(a,t,start,end):
    return a[(a.timestamp_ms>=start)&(a.timestamp_ms<end)]
def signal_stats(df, sig, cutoff, recent_start, max_station=None):
    x=df[(df.sensor_type==sig)&(df.timestamp_ms<cutoff)]
    if max_station is not None: x=x[x.station_index < max_station]
    h=stat(x.value); r=stat(x[x.timestamp_ms>=recent_start].value)
    return h,r
def feature_provenance(names, kind):
    rows=[]
    for n in names:
        source = "stations.csv" if n in {"station_id","station_archetype","base_cycle_time_ms","configured_cycle_std_ms","station_index","buffer_capacity","line_fraction"} else "station_events.csv"
        if any(s in n for s in ("torque","vibration","temperature","current")): source="sensor_readings.csv"
        if "manual" in n: source="manual_checks.csv"
        if kind == "defect":
            scope="source_station < prediction_station AND timestamp_ms < prediction_time; equal timestamps excluded"
            if n.startswith("cycle_"): definition="maximum or sample standard deviation of this unit's completed upstream cycle_time_ms before prediction"
            elif n.startswith("queue_"): definition="mean or sample standard deviation of queue_length_after across legally observed upstream station events; aggregate line context, not unit-specific"
            elif "manual" in n or n in {"last_manual_fail","stations_since_last_manual_fail"}: definition="cumulative/last legally observed manual check for this unit at upstream stations before prediction"
            elif any(x in n for x in ("torque","vibration","temperature","current")): definition=f"{n.split('_')[0].upper()} aggregate from legally observed upstream telemetry; recent window is [prediction_time-600000ms, prediction_time), history is all earlier legal observations"
            else: definition="unit or dynamically discovered topology context available at prediction"
            window="history: all legal observations; recent: [t-600000ms,t)"
        else:
            scope="same station, replayed station-event sequence through prediction event; telemetry/event values after prediction excluded"
            definition="configured topology value" if source=="stations.csv" else "causal 10-minute station-state aggregate; queue occupancy uses replayed queue_length_after because bufferCapacity applies to simulator buffer.size()"
            window="recent: [t-600000ms,t]; previous: [t-1200000ms,t-600000ms) where applicable"
            if n == "state_confidence":
                source="station_events.csv (derived)"
                definition="1.0 when this event's own queue_length_after was directly reported; otherwise exp(-elapsed_ms_since_last_direct_reading / 600000), i.e. causal decay toward 0 the longer occupancy has been carried forward without a fresh reading. 0.0 when no direct reading has ever been observed at this station yet."
                window="derived from all legally observed prior readings at this station; no lookahead"
            elif n == "progress_std":
                source="station_events.csv (derived)"
                definition="0.0 when this event's own queue_length_after was directly reported (no estimation error). Otherwise queue_std_10m (local occupancy volatility from the causal 10-minute window) scaled by sqrt(number of consecutive events since the last direct reading), a random-walk style growth of measurement/estimation uncertainty. NaN when no direct reading has ever been observed, or when queue_std_10m itself is unavailable."
                window="recent: [t-600000ms,t]; plus count of consecutive unobserved events since last direct reading"
            elif n == "eta_std":
                source="station_events.csv (derived)"
                definition="Standard error of the linear time-to-capacity estimate eta = capacity_headroom / queue_slope_10m, propagated via the delta method from (a) the regression standard error of queue_slope_10m over the causal 10-minute window and (b) progress_std as the uncertainty on current_occupancy/capacity_headroom. NaN whenever queue_slope_10m is undefined, non-positive (not trending toward capacity), or has fewer than 3 distinct causal observations to fit."
                window="recent: [t-600000ms,t]"
        rows.append({"feature_name":n,"exact_definition":definition,"formula":n, "source_file_table":source,"source_columns":"timestamp_ms, station_id, value/queue_length_after/cycle_time_ms where applicable","source_event_type":"raw observation","source_station_scope":scope,"source_timestamp_rule":scope,"history_recent_window":window,"aggregation":"deterministic mean, sample std, maximum, count, rate, or configured value","missingness_behavior":"NaN when observations are insufficient; current_missing_recent is 1 when recent CURRENT mean is unavailable","required_observation_count":1,"schema_version":SCHEMA_VERSION})
    return pd.DataFrame(rows)
def run_data(run):
    st=pd.read_csv(run/"stations.csv"); st["station_index"]=st.station_id.map(station_num)-1
    ev=pd.read_csv(run/"station_events.csv"); ev["station_index"]=ev.station_id.map(station_num)-1; ev["event_sequence"]=np.arange(len(ev)); ev.timestamp_ms=pd.to_numeric(ev.timestamp_ms)
    se=pd.read_csv(run/"sensor_readings.csv"); se["station_index"]=se.station_id.map(station_num)-1; se.timestamp_ms=pd.to_numeric(se.timestamp_ms); se.value=pd.to_numeric(se.value)
    ma=pd.read_csv(run/"manual_checks.csv"); ma["station_index"]=ma.station_id.map(station_num)-1; ma.timestamp_ms=pd.to_numeric(ma.timestamp_ms)
    ins=pd.read_csv(run/"inspection_results.csv"); ins["station_index"]=ins.station_id.map(station_num)-1; ins.timestamp_ms=pd.to_numeric(ins.timestamp_ms)
    un=pd.read_csv(run/"units.csv")
    return st,ev,se,ma,ins,un
def defect_rows(run_id, st, ev, se, ma, ins, un):
    entries=ev[ev.event_type.eq("UNIT_ARRIVED") & ev.unit_id.notna()].copy()
    # The entry event is the decision.  Strict < timestamp makes all equal-time cross-file
    # observations unavailable, the only safe rule because those files lack a shared sequence.
    final_index=int(st.station_index.max())
    out=[]; nstations=len(st)
    # Cache causal station-scope indexes and per-unit histories.  This changes only
    # execution cost: strict <t and station<s predicates remain identical.
    sensor_indexes={}; queue_indexes={}
    unit_cycles={unit: group for unit,group in ev[ev.event_type.eq("PROCESSING_COMPLETED")].groupby("unit_id",sort=False)}
    unit_manual={unit: group for unit,group in ma.groupby("unit_id",sort=False)}
    for e in entries.itertuples():
        ui=e.unit_id; s=e.station_index; t=e.timestamp_ms; recent=t-RECENT_MS
        # A unit's cycle history is unit-specific.  Queue history is intentionally
        # aggregate upstream line context and is documented as such in provenance.
        unit_cycle=unit_cycles.get(ui,ev.iloc[0:0]); hist_cycles=unit_cycle[(unit_cycle.station_index<s)&(unit_cycle.timestamp_ms<t)].cycle_time_ms.dropna()
        if s not in queue_indexes: queue_indexes[s]=TemporalStats(ev[ev.station_index<s],"queue_length_after")
        queues=queue_indexes[s].values(t)
        unit_check=unit_manual.get(ui,ma.iloc[0:0]); manual=unit_check[(unit_check.station_index<s)&(unit_check.timestamp_ms<t)]
        vals={"run_id":run_id,"unit_id":ui,"prediction_station":e.station_id,"prediction_time":t,"prediction_event_sequence":int(e.event_sequence),"prediction_station_index":s,"topology_configuration_version":SCHEMA_VERSION}
        for sig,prefix in [("TORQUE","torque"),("VIBRATION","vibration"),("TEMPERATURE","temperature"),("CURRENT","current")]:
            key=(sig,s)
            if key not in sensor_indexes: sensor_indexes[key]=TemporalStats(se[(se.sensor_type.eq(sig))&(se.station_index<s)],"value")
            h=sensor_indexes[key].values(t); r=sensor_indexes[key].values(t,recent); vals[f"{prefix}_mean_history"]=h[0]; vals[f"{prefix}_max_history"]=h[2]
            if prefix == "torque": vals["torque_std_history"] = h[1]
            vals[f"{prefix}_mean_recent"]=r[0]; vals[f"{prefix}_max_recent"]=r[2]
            if prefix in ("torque","vibration"): vals[f"{prefix}_delta_recent_vs_history"]=r[0]-h[0] if not(np.isnan(r[0]) or np.isnan(h[0])) else np.nan
        vals.update({"manual_fail_count_cum":int(manual.result.eq("FAIL").sum()),"line_fraction":s/max(1,nstations-1),"last_manual_fail":int(manual.result.eq("FAIL").iloc[-1]) if len(manual) else np.nan,"manual_check_count_cum":len(manual),"queue_history_mean":queues[0],"current_missing_recent":int(np.isnan(vals["current_mean_recent"])),"cycle_history_max":stat(hist_cycles)[2],"stations_since_last_manual_fail": (s-int(manual[manual.result.eq("FAIL")].station_index.iloc[-1])) if manual.result.eq("FAIL").any() else np.nan,"queue_history_std":queues[1],"cycle_history_std":stat(hist_cycles)[1]})
        unit=un[un.unit_id.eq(ui)].iloc[0]; vals["supplier_batch"]=unit.supplier_batch; vals["vehicle_model"]=unit.vehicle_model
        # Target-completeness fix: final inspection_results.csv is the authoritative
        # downstream source for y_defect.  The old builder additionally required a final-station
        # PROCESSING_COMPLETED event, which can incorrectly censor otherwise valid labels when
        # that event is absent.  QA is target-only: it is never used in X feature construction.
        final_qa=ins[(ins.unit_id.eq(ui))&(ins.station_index.eq(final_index))&(ins.timestamp_ms>=t)]
        complete=len(final_qa)>0
        vals["label_completeness_status"]="complete" if complete else "censored"; vals["y_defect"]=int(final_qa.result.eq("FAIL").any()) if complete else np.nan
        out.append(vals)
    df=pd.DataFrame(out)
    return df[["run_id","unit_id","prediction_station","prediction_time","prediction_event_sequence","topology_configuration_version","label_completeness_status"]+DEFECT_FEATURES+["y_defect"]]
def bottleneck_rows(run_id,st,ev):
    out=[]; cap=st.set_index("station_id").buffer_capacity.to_dict(); cfg=st.set_index("station_id")
    for station_id,g in ev.groupby("station_id",sort=False):
        g=g.sort_values(["timestamp_ms","event_sequence"]); capacity=float(cap[station_id]); idx=int(g.station_index.iloc[0]); c=cfg.loc[station_id]
        times=g.timestamp_ms.to_numpy(dtype=np.int64); sequences=g.event_sequence.to_numpy(dtype=np.int64); queue=pd.to_numeric(g.queue_length_after,errors="coerce").to_numpy(dtype=float); cycle=pd.to_numeric(g.cycle_time_ms,errors="coerce").to_numpy(dtype=float); types=g.event_type.to_numpy()
        qprefix=prefix_stats(queue); cprefix=prefix_stats(cycle); arrivals=np.r_[0,np.cumsum(types=="UNIT_ARRIVED")]; services=np.r_[0,np.cumsum(types=="PROCESSING_COMPLETED")]
        # Last observed queue state is the canonical replayed buffer occupancy.
        last_queue=np.where(np.isfinite(queue),queue,np.nan); last_queue=pd.Series(last_queue).ffill().fillna(0.).to_numpy()
        # Light-Zone observability bookkeeping: for each event, the index of the most
        # recent event (<= this one) whose OWN queue_length_after was directly reported.
        # This is a strictly causal prefix scan (no lookahead).
        observed_mask=np.isfinite(queue)
        last_obs_idx=np.where(observed_mask,np.arange(len(queue)),-1)
        last_obs_idx=np.maximum.accumulate(last_obs_idx)
        for i,t in enumerate(times):
            lo10=np.searchsorted(times,t-RECENT_MS,side="left"); lo20=np.searchsorted(times,t-2*RECENT_MS,side="left"); hi=i+1; prev_hi=lo10
            q10=range_stats(queue,qprefix,lo10,hi); qp=range_stats(queue,qprefix,lo20,prev_hi); c10=range_stats(cycle,cprefix,lo10,hi); occ=float(last_queue[i])
            arrivals10=int(arrivals[hi]-arrivals[lo10]); services10=int(services[hi]-services[lo10]); services_prev=int(services[prev_hi]-services[lo20])
            future_lo=np.searchsorted(times,t,side="right"); future_hi=np.searchsorted(times,t+HORIZON_MS,side="right"); future=queue[future_lo:future_hi]; over=np.nanmax(future) >= capacity if np.isfinite(future).any() else False; complete_horizon=times[-1]>=t+HORIZON_MS
            slope_mask=np.isfinite(queue[lo10:hi])
            slope_times=times[lo10:hi][slope_mask]
            slope_values=queue[lo10:hi][slope_mask]
            slope=np.nan; slope_std=np.nan
            distinct_slope_times=np.unique(slope_times).size
            if len(slope_times) > 1 and distinct_slope_times > 1:
                slope_x=slope_times.astype(float)-float(slope_times[0])
                fit=np.polyfit(slope_x, slope_values, 1); slope=float(fit[0])
                # eta_std needs a fitted-slope standard error.  Require at least three
                # distinct causal timestamps so the uncertainty is not spuriously zero.
                if distinct_slope_times >= 3:
                    residual=slope_values-(fit[0]*slope_x+fit[1]); dof=len(slope_x)-2
                    sxx=float(np.sum((slope_x-slope_x.mean())**2))
                    if dof>0 and sxx>0:
                        s_err=np.sqrt(np.sum(residual**2)/dof); slope_std=float(s_err/np.sqrt(sxx))
            # --- Light-Zone uncertainty features -------------------------------------
            oi=int(last_obs_idx[i])
            if observed_mask[i]:
                state_confidence=1.0; progress_std=0.0
            elif oi < 0:
                # No direct queue reading has ever been observed at this station yet.
                state_confidence=0.0; progress_std=np.nan
            else:
                elapsed=float(t-times[oi]); steps_missing=i-oi
                state_confidence=float(np.exp(-elapsed/RECENT_MS))
                vol=q10[1]
                progress_std=float(vol*np.sqrt(steps_missing)) if np.isfinite(vol) else np.nan
            headroom=capacity-occ
            eta_std=np.nan
            if (np.isfinite(slope) and slope>0 and np.isfinite(headroom)
                    and np.isfinite(slope_std) and np.isfinite(progress_std)):
                slope_term=(headroom/slope**2)**2 * slope_std**2
                state_term=(1.0/slope)**2 * progress_std**2
                eta_std=float(np.sqrt(slope_term+state_term))
            # --------------------------------------------------------------------------
            vals={"run_id":run_id,"station_id_buffer_id":station_id,"prediction_time":int(t),"prediction_event_sequence":int(sequences[i]),"station_index":idx,"capacity":capacity,"topology_configuration_version":SCHEMA_VERSION,"currently_at_capacity":bool(occ>=capacity),"target_eligibility_status":"eligible" if complete_horizon and occ<capacity else ("already_full" if occ>=capacity else "censored"),"capacity_headroom":capacity-occ,"station_id":station_id,"base_cycle_time_ms":c.base_cycle_time_ms,"station_archetype":c.archetype,"configured_cycle_std_ms":c.cycle_time_std_ms,"buffer_capacity":capacity,"line_fraction":idx/max(1,len(st)-1),"queue_max_10m":q10[2],"queue_mean_10m":q10[0],"current_occupancy":occ,"queue_std_10m":q10[1],"capacity_utilization":occ/capacity if capacity else np.nan,"arrival_rate_per_min_prev10m":int(arrivals[prev_hi]-arrivals[lo20])/10,"service_rate_per_min_prev10m":services_prev/10,"service_rate_per_min_10m":services10/10,"arrival_rate_per_min_10m":arrivals10/10,"utilization_headroom":1-occ/capacity if capacity else np.nan,"cycle_max_10m":c10[2],"flow_pressure_10m":arrivals10-services10,"queue_delta_10m":q10[0]-qp[0],"cycle_mean_10m":c10[0],"queue_slope_10m":slope,"net_flow_rate_10m":(arrivals10-services10)/10,"cycle_std_10m":c10[1],"state_confidence":state_confidence,"progress_std":progress_std,"eta_std":eta_std,"y_bottleneck":int(over) if complete_horizon and occ<capacity else np.nan}; out.append(vals)
    return pd.DataFrame(out)[["run_id","station_id_buffer_id","prediction_time","prediction_event_sequence","capacity","topology_configuration_version","currently_at_capacity","target_eligibility_status"]+BOTTLENECK_FEATURES+["y_bottleneck"]]

def fast_build_report(root, input_dir):
    """Vectorized preflight equivalent to the strict raw-data contract checks."""
    run_dirs=sorted(p for p in input_dir.glob("run_*") if p.is_dir())
    runs=[]
    for run in run_dirs:
        missing=sorted(name for name in REQUIRED_RAW_FILES if not (run/name).is_file())
        data={"run_id":run.name,"path":str(run),"missing_files":missing}
        if missing:
            runs.append(data); continue
        stations=pd.read_csv(run/"stations.csv")
        sensors=pd.read_csv(run/"sensor_readings.csv")
        events=pd.read_csv(run/"station_events.csv")
        metadata=json.loads((run/"run_metadata.json").read_text(encoding="utf-8"))
        sensor_types=sensors.sensor_type.astype(str).str.strip().str.upper()
        torque=sensors[sensor_types.eq("TORQUE")]
        ts_numeric=pd.to_numeric(torque.timestamp_ms,errors="coerce")
        val_numeric=pd.to_numeric(torque.value,errors="coerce")
        has_station=torque.station_id.notna() & torque.station_id.astype(str).str.strip().ne("")
        invalid=int((ts_numeric.isna()|val_numeric.isna()|~has_station).sum())
        row_count=int(len(torque))
        valid_mask=~(ts_numeric.isna()|val_numeric.isna()|~has_station)
        valid_ts=ts_numeric[valid_mask]
        data.update({
            "metadata_run_id":metadata.get("run_id"),
            "metadata_station_count":metadata.get("station_count"),
            "station_count_discovered":int(stations.station_id.nunique()),
            "station_ids":sorted(stations.station_id.astype(str).unique().tolist()),
            "sensor_columns":list(sensors.columns),
            "station_event_columns":list(events.columns),
            "sensor_signals":sorted(sensor_types.dropna().unique().tolist()),
            "torque_audit":{
                "row_count":row_count,
                "station_count":int(torque.loc[has_station,"station_id"].nunique()),
                "station_ids":sorted(torque.loc[has_station,"station_id"].astype(str).unique().tolist()),
                "timestamp_min_ms":int(valid_ts.min()) if len(valid_ts) else None,
                "timestamp_max_ms":int(valid_ts.max()) if len(valid_ts) else None,
                "invalid_or_missing_value_rows":invalid,
                "usable":row_count>0 and invalid==0,
            },
            "station_event_types":sorted(events.event_type.astype(str).str.strip().str.upper().dropna().unique().tolist()),
        })
        runs.append(data)
    all_signals=set().union(*(set(r.get("sensor_signals",[])) for r in runs)) if runs else set()
    missing_signal_runs={sig:[r["run_id"] for r in runs if sig not in set(r.get("sensor_signals",[]))] for sig in sorted(REQUIRED_SENSOR_SIGNALS)}
    violations=[]
    if not runs:
        violations.append({"rule":"raw-run-discovery","severity":"ERROR","detail":"No run_* directories found."})
    for r in runs:
        if r["missing_files"]:
            violations.append({"rule":"raw-schema","severity":"ERROR","run_id":r["run_id"],"detail":"Missing required raw file(s): "+", ".join(r["missing_files"])})
    for sig,absent in missing_signal_runs.items():
        if absent:
            affected=[n for n in DEFECT_FEATURES if n.startswith(sig.lower())]
            violations.append({"rule":"frozen-defect-feature-source","severity":"ERROR","signal":sig,"affected_features":affected,"runs":absent,"detail":f"Raw sensor_readings.csv for this input run does not export usable {sig}. No causal proxy or substituted signal is permitted."})
    from collections import Counter
    station_counts=Counter(r.get("station_count_discovered") for r in runs if "station_count_discovered" in r)
    return {
        "dataset_version":"pre-ml-causal-contract-v1",
        "feature_schema_version":"defect-30-v1 / bottleneck-28-v1",
        "causal_rule_version":"station-and-event-time-v1",
        "target_definition_version":"downstream-qa-v1 / future-overflow-30m-v1",
        "build_timestamp_utc":datetime.now(UTC).isoformat(),
        "git_commit":git(root),
        "input_root":str(input_dir),
        "runs_discovered":len(runs),
        "topology_summary":{"station_counts_discovered":dict(station_counts),"fixed_station_assumption":False},
        "required_defect_feature_count":len(DEFECT_FEATURES),
        "required_bottleneck_feature_count":len(BOTTLENECK_FEATURES),
        "available_sensor_signals_union":sorted(all_signals),
        "runs":runs,
        "causal_violations":violations,
        "materialization_permitted":not any(v["severity"]=="ERROR" for v in violations),
        "next_required_action":"Materialize the causal datasets from these validated raw runs." if not violations else "Correct the listed raw-data contract violations before materialization.",
        "validation_mode":"fast (vectorized pandas preflight)",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,default=Path("output"))
    p.add_argument("--output",type=Path,default=Path("causal_datasets"))
    p.add_argument("--validation",choices=["fast","strict","skip"],default="fast",help="fast: vectorized preflight. strict: original csv preflight. skip: skip preflight only; independent post-build replay still runs.")
    a=p.parse_args(); root=Path(__file__).resolve().parents[1]
    started=time.perf_counter()
    def progress(message): print(f"[{time.perf_counter()-started:8.1f}s] {message}",flush=True)
    if a.validation=="skip":
        progress("preflight validation skipped (--validation skip)")
        report={"materialization_permitted":True,"causal_violations":[],"validation_mode":"preflight skipped; post-build replay required"}
    else:
        progress(f"running {a.validation} preflight validation")
        report=slow_build_report(root,a.input.resolve()) if a.validation=="strict" else fast_build_report(root,a.input.resolve())
        progress(f"preflight complete in {time.perf_counter()-started:.1f}s")
    if not report["materialization_permitted"]:
        print(json.dumps(report["causal_violations"],indent=2),file=sys.stderr); return 2
    runs=sorted(p for p in a.input.glob("run_*") if p.is_dir())
    a.output.mkdir(parents=True,exist_ok=False); ds=[]; bs=[]
    progress(f"build started: {len(runs)} runs")
    for run_number,r in enumerate(runs,1):
        progress(f"run {run_number}/{len(runs)} {r.name}: loading raw data")
        st,ev,se,ma,ins,un=run_data(r)
        progress(f"run {run_number}/{len(runs)} {r.name}: defect features")
        defect=defect_rows(r.name,st,ev,se,ma,ins,un); ds.append(defect)
        progress(f"run {run_number}/{len(runs)} {r.name}: defect complete ({len(defect)} rows; total {sum(len(x) for x in ds)} rows)")
        progress(f"run {run_number}/{len(runs)} {r.name}: bottleneck features")
        # Boundary markers are runtime estimator controls, not LIGHT observations.
        bottleneck_ev=ev.loc[~ev.event_type.astype(str).str.upper().isin({"DARK_ZONE_ENTERED","DARK_ZONE_EXITED"})].copy()
        bottleneck=bottleneck_rows(r.name,st,bottleneck_ev); bs.append(bottleneck)
        progress(f"run {run_number}/{len(runs)} {r.name}: complete ({len(bottleneck)} bottleneck rows; total {sum(len(x) for x in bs)} rows)")
    d=pd.concat(ds,ignore_index=True); b=pd.concat(bs,ignore_index=True)
    if [x for x in d.columns if x in DEFECT_FEATURES] != DEFECT_FEATURES or len(set(d.columns)) != len(d.columns): raise RuntimeError("defect frozen feature projection is missing, reordered, or duplicated")
    if [x for x in b.columns if x in BOTTLENECK_FEATURES] != BOTTLENECK_FEATURES or len(set(b.columns)) != len(b.columns): raise RuntimeError("bottleneck frozen feature projection is missing, reordered, or duplicated")
    dp=feature_provenance(DEFECT_FEATURES,"defect"); bp=feature_provenance(BOTTLENECK_FEATURES,"bottleneck")
    if set(dp.feature_name)!=set(DEFECT_FEATURES) or set(bp.feature_name)!=set(BOTTLENECK_FEATURES): raise RuntimeError("feature provenance is incomplete")
    progress(f"writing artifacts ({len(d)} defect rows, {len(b)} bottleneck rows)")
    d.to_parquet(a.output/"defect_causal_features.parquet",index=False)
    b.to_parquet(a.output/"bottleneck_causal_features.parquet",index=False)
    dp.to_csv(a.output/"defect_feature_provenance.csv",index=False)
    bp.to_csv(a.output/"bottleneck_feature_provenance.csv",index=False)
    progress("independent post-build causal replay validation")
    validation=validate(a.output,a.input)
    report.update({
        "materialization_permitted":bool(validation["passed"]),
        "defect_rows":len(d),
        "bottleneck_rows":len(b),
        "defect_feature_count":len(DEFECT_FEATURES),
        "bottleneck_feature_count":len(BOTTLENECK_FEATURES),
        "recent_window_ms":RECENT_MS,
        "previous_window_ms":RECENT_MS,
        "git_commit":git(root),
        "independent_validation":validation,
        "causal_violations":validation["causal_violations"],
    })
    (a.output/"causal_audit_report.json").write_text(json.dumps(report,indent=2))
    (a.output/"dataset_summary.json").write_text(json.dumps({
        "dataset_version":SCHEMA_VERSION,
        "defect_columns":DEFECT_FEATURES,
        "bottleneck_columns":BOTTLENECK_FEATURES,
        "build_timestamp_utc":datetime.now(UTC).isoformat(),
        "independent_validation_passed":validation["passed"],
    },indent=2))
    if not validation["passed"]:
        raise RuntimeError("independent causal validation failed; inspect causal_audit_report.json")
    progress(f"build complete: {a.output}")
    print(a.output)
    return 0

if __name__=="__main__": raise SystemExit(main())
