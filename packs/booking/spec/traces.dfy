// traces.dfy — concrete accepting and rejecting traces, executed against the verified core (`dafny test`).
// They are the trace-review artifacts the roadmap asks authors to read before sealing a pack: each one is a
// concrete case a reader can check against INTENT.md by hand, and each known-wrong core in wrong/ behaves
// differently from the core on at least one of them (named in the comment).
include "BookingCore.dfy"

module Traces {
  import opened BookingSpec
  import opened BookingCore

  method {:test} T1_TouchingIntervalsAreBothAccepted() {       // wrong/closed_intervals.dfy refuses the second
    var k := new Core();
    var o1, c1 := k.Book([], 1, 600, 660);                       // 10:00-11:00
    var o2, c2 := k.Book(c1, 2, 660, 720);                       // 11:00-12:00 starts exactly when 1 ends
    expect o1 == Accepted && o2 == Accepted;
    expect |c2| == 2;
  }

  method {:test} T2_OverlapIsRefusedAndNamesTheBlocker() {     // wrong/conflict_names_requester.dfy names 3
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var o, c2 := k.Book(c1, 3, 630, 690);
    expect o == Conflict(1);
    expect c2 == c1;
  }

  method {:test} T3_ContainingIntervalIsRefused() {            // wrong/start_inside_only.dfy accepts it
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var o, c2 := k.Book(c1, 2, 540, 720);                       // 09:00-12:00 contains 10:00-11:00
    expect o == Conflict(1) && c2 == c1;
  }

  method {:test} T4_EmptyAndReversedIntervalsAreInvalid() {
    var k := new Core();
    var o1, c1 := k.Book([], 1, 600, 600);
    var o2, c2 := k.Book(c1, 2, 660, 600);
    var o3, c3 := k.Book(c2, 3, 600, 601);                      // one minute is the shortest valid booking
    expect o1 == Invalid && o2 == Invalid && c2 == [];
    expect o3 == Accepted && c3 == [Slot(3, 600, 601, true)];
  }

  method {:test} T5_CancelFreesTheIntervalAndIsTerminal() {    // wrong/cancel_toggles.dfy revives 1 on the second cancel
    var k := new Core();
    var _, c0 := k.Book([], 1, 600, 660);
    var _, c1 := k.Book(c0, 5, 660, 720);                       // a second booking, which the cancel must leave alone
    var ok1, c2 := k.Cancel(c1, 1);
    var ok2, c3 := k.Cancel(c2, 1);
    var ok3, c5 := k.Cancel(c3, 9);                             // an unknown id changes nothing
    var o, c4 := k.Book(c3, 2, 600, 660);
    expect ok1 && !ok2 && c3 == c2 && !ok3 && c5 == c3;
    expect !c2[0].active && c2[1] == Slot(5, 660, 720, true);
    expect o == Accepted && |c4| == 3 && !c4[0].active && c4[1].active && c4[2].active;
  }

  method {:test} T6_MoveWithinItsOwnTimeIsAccepted() {         // wrong/reschedule_blocks_itself.dfy refuses it
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 720);
    var o, c2 := k.Reschedule(c1, 1, 630, 690);
    expect o == Accepted && c2 == [Slot(1, 630, 690, true)];
    var _, d1 := k.Book([], 1, 600, 660);
    var _, d2 := k.Book(d1, 2, 690, 750);
    var p, d3 := k.Reschedule(d2, 1, 630, 690);                 // shift (not shrink) over its own time, ending where 2 starts
    expect p == Accepted && d3 == [Slot(1, 630, 690, true), Slot(2, 690, 750, true)];
  }

  method {:test} T7_RefusedMoveKeepsTheOriginal() {            // wrong/reschedule_cancel_then_book.dfy loses booking 1
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var _, c2 := k.Book(c1, 2, 660, 720);
    var o, c3 := k.Reschedule(c2, 1, 630, 690);
    expect o == Conflict(2) && c3 == c2 && c3[0].active;
  }

  method {:test} T8_CancelledBookingCannotMove() {
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var _, c2 := k.Cancel(c1, 1);
    var o, c3 := k.Reschedule(c2, 1, 700, 760);
    expect o == NotActive && c3 == c2;
  }

  method {:test} T9_TouchingFromBelowIsAccepted() {            // wrong/closed_at_end.dfy refuses the second
    var k := new Core();
    var o1, c1 := k.Book([], 1, 600, 660);
    var o2, c2 := k.Book(c1, 2, 540, 600);                      // 09:00-10:00 ends exactly when 1 starts
    expect o1 == Accepted && o2 == Accepted && |c2| == 2;
  }

  method {:test} T10_OneMinuteOverlapConflicts() {             // wrong/ignores_one_minute_overlap.dfy accepts both
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var o, c2 := k.Book(c1, 2, 659, 720);                       // starts one minute before 1 ends
    var p, c3 := k.Book(c1, 3, 540, 601);                       // ends one minute after 1 starts
    expect o == Conflict(1) && p == Conflict(1) && c2 == c1 && c3 == c1;
  }

  method {:test} T11_MoveRefusalsAndTheirOrder() {             // not-active is reported before an invalid interval
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var o1, d1 := k.Reschedule(c1, 1, 700, 700);                // active, empty interval
    var o2, d2 := k.Reschedule(c1, 9, 700, 760);                // unknown id
    var _, c2 := k.Cancel(c1, 1);
    var o3, d3 := k.Reschedule(c2, 1, 700, 690);                // cancelled AND reversed: NotActive wins
    expect o1 == Invalid && d1 == c1 && o2 == NotActive && d2 == c1 && o3 == NotActive && d3 == c2;
  }
}
