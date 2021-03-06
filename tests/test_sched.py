# coding: utf-8

import time, copy
from tests.shared import assertException, getEmptyDeck
from anki.stdmodels import BasicModel
from anki.utils import stripHTML, intTime
from anki.hooks import addHook

def test_basics():
    d = getEmptyDeck()
    assert not d.sched.getCard()

def test_new():
    d = getEmptyDeck()
    assert d.sched.newCount == 0
    # add a fact
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    d.addFact(f)
    d.reset()
    assert d.sched.newCount == 1
    # fetch it
    c = d.sched.getCard()
    assert c
    assert c.queue == 0
    assert c.type == 0
    # if we answer it, it should become a learn card
    t = intTime()
    d.sched.answerCard(c, 1)
    assert c.queue == 1
    assert c.type == 1
    assert c.due >= t
    # the default order should ensure siblings are not seen together, and
    # should show all cards
    m = d.currentModel()
    m.templates[1]['actv'] = True
    m.flush()
    f = d.newFact()
    f['Front'] = u"2"; f['Back'] = u"2"
    d.addFact(f)
    f = d.newFact()
    f['Front'] = u"3"; f['Back'] = u"3"
    d.addFact(f)
    d.reset()
    qs = ("2", "3", "2", "3")
    for n in range(4):
        c = d.sched.getCard()
        assert(stripHTML(c.q()) == qs[n])
        d.sched.answerCard(c, 2)

def test_newOrder():
    d = getEmptyDeck()
    m = d.currentModel()
    for i in range(50):
        t = m.newTemplate()
        t['name'] = str(i)
        t['qfmt'] = "{{Front}}"
        t['afmt'] = "{{Back}}"
        t['actv'] = i > 25
        m.addTemplate(t)
    m.flush()
    f = d.newFact()
    f['Front'] = u'1'
    f['Back'] = u'2'
    # add first half
    d.addFact(f)
    # generate second half
    d.db.execute("update cards set gid = random()")
    d.qconf['newPerDay'] = 100
    d.reset()
    # cards should be sorted by id
    assert d.sched.newQueue == list(reversed(sorted(d.sched.newQueue)))

def test_newBoxes():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    d.reset()
    c = d.sched.getCard()
    d.sched.answerCard(c, 2)
    assert c.grade == 1
    d.sched._cardConf(c)['new']['delays'] = [0.5]
    # should handle gracefully
    d.sched.answerCard(c, 2)

def test_learn():
    d = getEmptyDeck()
    # add a fact
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    f = d.addFact(f)
    # set as a learn card and rebuild queues
    d.db.execute("update cards set queue=0, type=0")
    d.reset()
    # sched.getCard should return it, since it's due in the past
    c = d.sched.getCard()
    assert c
    d.sched._cardConf(c)['new']['delays'] = [0.5, 3, 10]
    # it should have no cycles and a grade of 0
    assert c.grade == c.cycles == 0
    # fail it
    d.sched.answerCard(c, 1)
    # it should by due in 30 seconds
    t = round(c.due - time.time())
    assert t >= 30 and t <= 40
    # and have 1 cycle, but still a zero grade
    assert c.grade == 0
    assert c.cycles == 1
    # pass it once
    d.sched.answerCard(c, 2)
    # it should by due in 3 minutes
    assert round(c.due - time.time()) in (179, 180)
    # and it should be grade 1 now
    assert c.grade == 1
    assert c.cycles == 2
    # check log is accurate
    log = d.db.first("select * from revlog order by time desc")
    assert log[2] == 2
    assert log[3] == -180
    assert log[4] == -30
    # pass again
    d.sched.answerCard(c, 2)
    # it should by due in 10 minutes
    assert round(c.due - time.time()) in (599, 600)
    # and it should be grade 1 now
    assert c.grade == 2
    assert c.cycles == 3
    # the next pass should graduate the card
    assert c.queue == 1
    assert c.type == 1
    d.sched.answerCard(c, 2)
    assert c.queue == 2
    assert c.type == 2
    # should be due tomorrow, with an interval of 1
    assert c.due == d.sched.today+1
    assert c.ivl == 1
    # let's try early removal bonus
    c.type = 0
    c.queue = 1
    c.cycles = 0
    d.sched.answerCard(c, 3)
    assert c.type == 2
    assert c.ivl == 7
    # or normal removal
    c.type = 0
    c.queue = 1
    c.cycles = 1
    d.sched.answerCard(c, 3)
    assert c.type == 2
    assert c.queue == 2
    assert c.ivl == 4
    # revlog should have been updated each time
    d.db.scalar("select count() from revlog where type = 0") == 6
    # now failed card handling
    c.type = 2
    c.queue = 1
    c.edue = 123
    d.sched.answerCard(c, 3)
    assert c.due == 123
    assert c.type == 2
    assert c.queue == 2
    # we should be able to remove manually, too
    c.type = 2
    c.queue = 1
    c.edue = 321
    c.flush()
    d.sched.removeFailed()
    c.load()
    assert c.queue == 2
    assert c.due == 321

def test_reviews():
    d = getEmptyDeck()
    # add a fact
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    d.addFact(f)
    # set the card up as a review card, due yesterday
    c = f.cards()[0]
    c.type = 2
    c.queue = 2
    c.due = d.sched.today - 8
    c.factor = 2500
    c.reps = 3
    c.streak = 2
    c.lapses = 1
    c.ivl = 100
    c.startTimer()
    c.flush()
    # save it for later use as well
    cardcopy = copy.copy(c)
    # failing it should put it in the learn queue with the default options
    ##################################################
    d.sched.answerCard(c, 1)
    assert c.queue == 1
    # it should be due tomorrow, with an interval of 1
    assert c.edue == d.sched.today + 1
    assert c.ivl == 1
    # but because it's in the learn queue, its current due time should be in
    # the future
    assert c.due >= time.time()
    # factor should have been decremented
    assert c.factor == 2300
    # check counters
    assert c.lapses == 2
    assert c.reps == 4
    # try again with an ease of 2 instead
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    d.sched.answerCard(c, 2)
    assert c.queue == 2
    # the new interval should be (100 + 8/4) * 1.2 = 122
    assert c.ivl == 122
    assert c.due == d.sched.today + 122
    # factor should have been decremented
    assert c.factor == 2350
    # check counters
    assert c.lapses == 1
    assert c.reps == 4
    # ease 3
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    d.sched.answerCard(c, 3)
    # the new interval should be (100 + 8/2) * 2.5 = 260
    assert c.ivl == 260
    assert c.due == d.sched.today + 260
    # factor should have been left alone
    assert c.factor == 2500
    # ease 4
    ##################################################
    c = copy.copy(cardcopy)
    c.flush()
    d.sched.answerCard(c, 4)
    # the new interval should be (100 + 8) * 2.5 * 1.3 = 351
    assert c.ivl == 351
    assert c.due == d.sched.today + 351
    # factor should have been increased
    assert c.factor == 2650
    # leech handling
    ##################################################
    c = copy.copy(cardcopy)
    c.lapses = 15
    c.flush()
    # steup hook
    hooked = []
    def onLeech(card):
        hooked.append(1)
    addHook("leech", onLeech)
    d.sched.answerCard(c, 1)
    assert hooked
    assert c.queue == -1
    c.load()
    assert c.queue == -1

def test_finished():
    d = getEmptyDeck()
    # nothing due
    assert "No cards are due" in d.sched.finishedMsg()
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    d.addFact(f)
    # have a new card
    assert "1 new" in d.sched.finishedMsg()
    # turn it into a review
    c = f.cards()[0]
    c.startTimer()
    d.sched.answerCard(c, 3)
    # nothing should be due tomorrow, as it's due in a week
    assert "No cards are due" in d.sched.finishedMsg()

def test_nextIvl():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    d.addFact(f)
    c = f.cards()[0]
    d.sched._cardConf(c)['new']['delays'] = [0.5, 3, 10]
    d.sched._cardConf(c)['lapse']['delays'] = [0.5, 3, 10]
    # cards in learning
    ##################################################
    ni = d.sched.nextIvl
    assert ni(c, 1) == 30
    assert ni(c, 2) == 180
    # immediate removal is 7 days
    assert ni(c, 3) == 7*86400
    c.cycles = 1
    c.grade = 1
    assert ni(c, 1) == 30
    assert ni(c, 2) == 600
    # no first time bonus
    assert ni(c, 3) == 4*86400
    c.grade = 2
    # normal graduation is tomorrow
    assert ni(c, 2) == 1*86400
    assert ni(c, 3) == 4*86400
    # lapsed cards
    ##################################################
    c.type = 2
    c.ivl = 100
    c.factor = 2500
    assert ni(c, 1) == 30
    assert ni(c, 2) == 100*86400
    assert ni(c, 3) == 100*86400
    # review cards
    ##################################################
    c.queue = 2
    c.ivl = 100
    c.factor = 2500
    # failing it should put it at 30s
    assert ni(c, 1) == 30
    # or 1 day if relearn is false
    d.sched._cardConf(c)['lapse']['relearn']=False
    assert ni(c, 1) == 1*86400
    # (* 100 1.2 86400)10368000.0
    assert ni(c, 2) == 10368000
    # (* 100 2.5 86400)21600000.0
    assert ni(c, 3) == 21600000
    # (* 100 2.5 1.3 86400)28080000.0
    assert ni(c, 4) == 28080000
    assert d.sched.nextIvlStr(c, 4) == "10.8 months"

def test_misc():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    c = f.cards()[0]
    # burying
    d.sched.buryFact(c.fid)
    d.reset()
    assert not d.sched.getCard()
    d.sched.onClose()
    d.reset()
    assert d.sched.getCard()
    # counts
    assert d.sched.timeToday() == 0
    assert d.sched.repsToday() == 0
    c.timerStarted = time.time() - 10
    d.sched.answerCard(c, 2)
    assert d.sched.timeToday() > 0
    assert d.sched.repsToday() == 1

def test_suspend():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    c = f.cards()[0]
    # suspending
    d.reset()
    assert d.sched.getCard()
    d.sched.suspendCards([c.id])
    d.reset()
    assert not d.sched.getCard()
    # unsuspending
    d.sched.unsuspendCards([c.id])
    d.reset()
    assert d.sched.getCard()
    # should cope with rev cards being relearnt
    c.due = 0; c.ivl = 100; c.type = 2; c.queue = 2; c.flush()
    d.reset()
    c = d.sched.getCard()
    d.sched.answerCard(c, 1)
    assert c.due >= time.time()
    assert c.queue == 1
    assert c.type == 2
    d.sched.suspendCards([c.id])
    d.sched.unsuspendCards([c.id])
    c.load()
    assert c.queue == 2
    assert c.type == 2
    assert c.due == 1

def test_cram():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    c = f.cards()[0]
    c.ivl = 100
    c.type = c.queue = 2
    # due in 25 days, so it's been waiting 75 days
    c.due = d.sched.today + 25
    c.mod = 1
    c.startTimer()
    c.flush()
    cardcopy = copy.copy(c)
    d.qconf['groups'] = [1]
    d.cramGroups()
    # first, test with initial intervals preserved
    conf = d.sched._lrnConf(c)
    conf['reset'] = False
    conf['resched'] = False
    assert d.sched.counts() == (1, 0, 0)
    c = d.sched.getCard()
    d.sched._cardConf(c)['cram']['delays'] = [0.5, 3, 10]
    assert d.sched.counts() == (0, 0, 0)
    # check that estimates work
    assert d.sched.nextIvl(c, 1) == 30
    assert d.sched.nextIvl(c, 2) == 180
    assert d.sched.nextIvl(c, 3) == 86400*100
    # failing it should not reset ivl
    assert c.ivl == 100
    d.sched.answerCard(c, 1)
    assert c.ivl == 100
    # and should have incremented lrn count
    assert d.sched.counts()[1] == 1
    # reset ivl for exit test, and pass card
    d.sched.answerCard(c, 2)
    delta = c.due - time.time()
    assert delta > 175 and delta <= 180
    # another two answers should reschedule it
    assert c.queue == 1
    d.sched.answerCard(c, 2)
    d.sched.answerCard(c, 2)
    assert c.queue == -3
    assert c.ivl == 100
    assert c.due == d.sched.today + c.ivl
    # and if the queue is reset, it shouldn't appear in the new queue again
    d.reset()
    assert d.sched.counts() == (0, 0, 0)
    # now try again with ivl rescheduling
    c = copy.copy(cardcopy)
    c.flush()
    d.cramGroups()
    conf = d.sched._lrnConf(c)
    conf['reset'] = False
    conf['resched'] = True
    # failures shouldn't matter
    d.sched.answerCard(c, 1)
    # graduating the card will keep the same interval, but shift the card
    # forward the number of days it had been waiting (75)
    assert d.sched.nextIvl(c, 3) == 75*86400
    d.sched.answerCard(c, 3)
    assert c.ivl == 100
    assert c.due == d.sched.today + 75
    # try with ivl reset
    c = copy.copy(cardcopy)
    c.flush()
    d.cramGroups()
    conf = d.sched._lrnConf(c)
    conf['reset'] = True
    conf['resched'] = True
    d.sched.answerCard(c, 1)
    assert d.sched.nextIvl(c, 3) == 1*86400
    d.sched.answerCard(c, 3)
    assert c.ivl == 1
    assert c.due == d.sched.today + 1
    # users should be able to cram entire deck too
    d.qconf['groups'] = []
    d.cramGroups()
    assert d.sched.counts()[0] > 0

def test_cramLimits():
    d = getEmptyDeck()
    # create three cards, due tomorrow, the next, etc
    for i in range(3):
        f = d.newFact()
        f['Front'] = str(i)
        d.addFact(f)
        c = f.cards()[0]
        c.type = c.queue = 2
        c.due = d.sched.today + 1 + i
        c.flush()
    # the default cram should return all three
    d.qconf['groups'] = [1]
    d.cramGroups()
    assert d.sched.counts()[0] == 3
    # if we start from the day after tomorrow, it should be 2
    d.cramGroups(min=1)
    assert d.sched.counts()[0] == 2
    # or after 2 days
    d.cramGroups(min=2)
    assert d.sched.counts()[0] == 1
    # we may get nothing
    d.cramGroups(min=3)
    assert d.sched.counts()[0] == 0
    # tomorrow(0) + dayAfter(1) = 2
    d.cramGroups(max=1)
    assert d.sched.counts()[0] == 2
    # if max is tomorrow, we get only one
    d.cramGroups(max=0)
    assert d.sched.counts()[0] == 1
    # both should work
    d.cramGroups(min=0, max=0)
    assert d.sched.counts()[0] == 1
    d.cramGroups(min=1, max=1)
    assert d.sched.counts()[0] == 1
    d.cramGroups(min=0, max=1)
    assert d.sched.counts()[0] == 2

def test_adjIvl():
    d = getEmptyDeck()
    # add two more templates and set second active
    m = d.currentModel()
    m.templates[1]['actv'] = True
    t = m.newTemplate()
    t['name'] = "f2"
    t['qfmt'] = "{{Front}}"
    t['afmt'] = "{{Back}}"
    m.addTemplate(t)
    t = m.newTemplate()
    t['name'] = "f3"
    t['qfmt'] = "{{Front}}"
    t['afmt'] = "{{Back}}"
    m.addTemplate(t)
    m.flush()
    # create a new fact; it should have 4 cards
    f = d.newFact()
    f['Front'] = "1"; f['Back'] = "1"
    d.addFact(f)
    assert d.cardCount() == 4
    d.reset()
    # immediately remove first; it should get ideal ivl
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 7
    # with the default settings, second card should be -1
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 6
    # and third +1
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 8
    # fourth exceeds default settings, so gets ideal again
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 7
    # try again with another fact
    f = d.newFact()
    f['Front'] = "2"; f['Back'] = "2"
    d.addFact(f)
    d.reset()
    # set a minSpacing of 0
    conf = d.sched._cardConf(c)
    conf['rev']['minSpace'] = 0
    # first card gets ideal
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 7
    # and second too, because it's below the threshold
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 7
    # if we increase the ivl minSpace isn't needed
    conf['new']['ints'][1] = 20
    # ideal..
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 20
    # adjusted
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert c.ivl == 19

def test_ordcycle():
    d = getEmptyDeck()
    # add two more templates and set second active
    m = d.currentModel()
    m.templates[1]['actv'] = True
    t = m.newTemplate()
    t['name'] = "f2"
    t['qfmt'] = "{{Front}}"
    t['afmt'] = "{{Back}}"
    m.addTemplate(t)
    m.flush()
    # create a new fact; it should have 4 cards
    f = d.newFact()
    f['Front'] = "1"; f['Back'] = "1"
    d.addFact(f)
    assert d.cardCount() == 3
    d.reset()
    # ordinals should arrive in order
    assert d.sched.getCard().ord == 0
    assert d.sched.getCard().ord == 1
    assert d.sched.getCard().ord == 2

def test_counts():
    d = getEmptyDeck()
    # add a second group
    assert d.groupId("new group") == 2
    # for each card type
    for type in range(3):
        # and each of the groups
        for gid in (1,2):
            # create a new fact
            f = d.newFact()
            f['Front'] = u"one"
            d.addFact(f)
            c = f.cards()[0]
            # set type/gid
            c.type = type
            c.queue = type
            c.gid = gid
            c.due = 0
            c.flush()
    d.reset()
    # with the default settings, there's no count limit
    assert d.sched.counts() == (2,2,2)
    # check limit to one group
    d.qconf['groups'] = [1]
    d.reset()
    assert d.sched.counts() == (1,1,1)
    # we don't need to build the queue to get the counts
    assert d.sched.allCounts() == (2,2,2)
    assert d.sched.selCounts() == (1,1,1)
    assert d.sched.allCounts() == (2,2,2)

def test_counts2():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"; f['Back'] = u"two"
    d.addFact(f)
    d.reset()
    assert d.sched.counts() == (1, 0, 0)
    c = d.sched.getCard()
    # counter's been decremented but idx indicates 1
    assert d.sched.counts() == (0, 0, 0)
    assert d.sched.countIdx(c) == 0
    # answer to move to learn queue
    d.sched.answerCard(c, 1)
    assert d.sched.counts() == (0, 1, 0)
    # fetching again will decrement the count
    c = d.sched.getCard()
    assert d.sched.counts() == (0, 0, 0)
    assert d.sched.countIdx(c) == 1
    # answering should add it back again
    d.sched.answerCard(c, 1)
    assert d.sched.counts() == (0, 1, 0)

def test_timing():
    d = getEmptyDeck()
    # add a few review cards, due today
    for i in range(5):
        f = d.newFact()
        f['Front'] = "num"+str(i)
        d.addFact(f)
        c = f.cards()[0]
        c.type = 2
        c.queue = 2
        c.due = 0
        c.flush()
    # fail the first one
    d.reset()
    c = d.sched.getCard()
    # set a a fail delay of 1 second so we don't have to wait
    d.sched._cardConf(c)['lapse']['delays'][0] = 1/60.0
    d.sched.answerCard(c, 1)
    # the next card should be another review
    c = d.sched.getCard()
    assert c.queue == 2
    # but if we wait for a second, the failed card should come back
    time.sleep(1)
    c = d.sched.getCard()
    assert c.queue == 1

def test_collapse():
    d = getEmptyDeck()
    # add a fact
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    d.reset()
    # test collapsing
    c = d.sched.getCard()
    d.sched.answerCard(c, 1)
    c = d.sched.getCard()
    d.sched.answerCard(c, 3)
    assert not d.sched.getCard()

def test_groupCounts():
    d = getEmptyDeck()
    # add a fact with default group
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    # and one that's a child
    f = d.newFact()
    f['Front'] = u"two"
    f.gid = d.groupId("Default::1")
    d.addFact(f)
    # make it a review card
    c = f.cards()[0]
    c.queue = 2
    c.due = 0
    c.flush()
    # add one more with a new group
    f = d.newFact()
    f['Front'] = u"two"
    f.gid = d.groupId("foo::bar")
    d.addFact(f)
    # and one that's a sibling
    f = d.newFact()
    f['Front'] = u"three"
    f.gid = d.groupId("foo::baz")
    d.addFact(f)
    d.reset()
    assert d.sched.counts() == (3, 0, 1)
    assert len(d.groups()) == 4
    cnts = d.sched.groupCounts()
    assert cnts[0] == ["Default", 1, 1, 0, 1]
    assert cnts[1] == ["Default::1", 2, 1, 1, 0]
    assert cnts[2] == ["foo::bar", 3, 1, 0, 1]
    assert cnts[3] == ["foo::baz", 4, 1, 0, 1]
    tree = d.sched.groupCountTree()
    assert tree[0][0] == "Default"
    # sum of child and parent
    assert tree[0][1] == 1
    assert tree[0][2] == 2
    assert tree[0][3] == 1
    assert tree[0][4] == 1
    # child count is just review
    assert tree[0][5][0][0] == "1"
    assert tree[0][5][0][1] == 2
    assert tree[0][5][0][2] == 1
    assert tree[0][5][0][3] == 1
    assert tree[0][5][0][4] == 0
    # event if parent group didn't exist, it should have been created with a
    # counts summary, with an empty gid
    assert tree[1][0] == "foo"
    assert tree[1][1] == None
    assert tree[1][2] == 2
    assert tree[1][3] == 0
    assert tree[1][4] == 2

def test_reorder():
    d = getEmptyDeck()
    # add a fact with default group
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    f2 = d.newFact()
    f2['Front'] = u"two"
    d.addFact(f2)
    assert f2.cards()[0].due == f2.id
    found=False
    # 50/50 chance of being reordered
    for i in range(20):
        d.sched.randomizeCards()
        if f.cards()[0].due != f.id:
            found=True
            break
    assert found
    d.sched.orderCards()
    assert f.cards()[0].due == f.id
    # shifting
    f3 = d.newFact()
    f3['Front'] = u"three"
    d.addFact(f3)
    f4 = d.newFact()
    f4['Front'] = u"four"
    d.addFact(f4)
    assert f.cards()[0].due == 1
    assert f2.cards()[0].due == 2
    assert f3.cards()[0].due == 3
    assert f4.cards()[0].due == 4
    d.sched.sortCards([
        f3.cards()[0].id, f4.cards()[0].id], start=1, shift=True)
    assert f.cards()[0].due == 3
    assert f2.cards()[0].due == 4
    assert f3.cards()[0].due == 1
    assert f4.cards()[0].due == 2

def test_forget():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    c = f.cards()[0]
    c.queue = 2; c.type = 2; c.ivl = 100; c.due = 0
    c.flush()
    d.reset()
    assert d.sched.counts() == (0, 0, 1)
    d.sched.forgetCards([c.id])
    d.reset()
    assert d.sched.counts() == (1, 0, 0)

def test_resched():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    c = f.cards()[0]
    d.sched.reschedCards([c.id], 0, 0)
    c.load()
    assert c.due == d.sched.today
    assert c.ivl == 1
    assert c.queue == c.type == 2
    d.sched.reschedCards([c.id], 1, 1)
    c.load()
    assert c.due == d.sched.today+1
    assert c.ivl == +1

def test_eta():
    d = getEmptyDeck()
    f = d.newFact()
    f['Front'] = u"one"
    d.addFact(f)
    d.reset()
    c = d.sched.getCard()
    time.sleep(0.1)
    d.sched.answerCard(c, 1)
    time.sleep(0.1)
    d.sched.answerCard(c, 1)
