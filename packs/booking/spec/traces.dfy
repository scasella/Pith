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
    expect o1 == Invalid && o2 == Invalid && c2 == [];
  }

  method {:test} T5_CancelFreesTheIntervalAndIsTerminal() {    // wrong/cancel_toggles.dfy revives 1 on the second cancel
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 660);
    var ok1, c2 := k.Cancel(c1, 1);
    var ok2, c3 := k.Cancel(c2, 1);
    var o, c4 := k.Book(c3, 2, 600, 660);
    expect ok1 && !ok2 && c3 == c2;
    expect o == Accepted && |c4| == 2 && !c4[0].active && c4[1].active;
  }

  method {:test} T6_MoveWithinItsOwnTimeIsAccepted() {         // wrong/reschedule_blocks_itself.dfy refuses it
    var k := new Core();
    var _, c1 := k.Book([], 1, 600, 720);
    var o, c2 := k.Reschedule(c1, 1, 630, 690);
    expect o == Accepted && c2 == [Slot(1, 630, 690, true)];
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
}
