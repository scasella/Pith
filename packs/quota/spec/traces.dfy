// traces.dfy — every reviewed trace in TraceData.dfy, run against the verified core (`dafny test`, check core.traces).
include "QuotaCore.dfy"
include "TraceData.dfy"

module CoreTraces {
  import opened QuotaSpec
  import opened QuotaCore
  import opened QuotaTraces

  method {:test} AllTracesHoldForTheCore() {
    var all := All();
    expect |all| == 10;
    var i := 0;
    while i < |all| {
      var core := new Core();
      var m := Run(core, all[i]);
      if m != -1 { print "trace ", all[i].name, " differs at step ", m, "\n"; }
      expect m == -1;
      i := i + 1;
    }
    print "traces: ", |all|, " hold\n";
  }
}
