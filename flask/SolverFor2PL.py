
import itertools
import sys

from Scheduler import formatSchedule
from Actions import Action


def solve2PL(schedule, use_xl_only):

    print(schedule, use_xl_only, file=sys.stderr)

    # initialize set of transactions and objects
    transactions = set([op.id_transaction for op in schedule])
    objects = set([op.object for op in schedule])

    # states[transaction][object] = state of object from the perspective of transaction (number of states = |transactions|x|objects|)
    # a state can be 'START', 'SHARED_LOCK', 'XCLUSIVE_L', 'UNLOCKED'
    states = {tx: {o: 'START' for o in objects} for tx in transactions}

    # state of the transaction, if it is in the growing or shrinking phase (#locks)
    transaction_state = {tx: 'GROWING' for tx in transactions}

    # flags that check if the schedule is 2PL-strict
    # set to true when the transaction unlocks the first exclusive lock
    has_x_unlocked = {tx: False for tx in transactions}
    # set to false if any transaction has xunlocked but after performs another action
    is_strict = True

    # flags that check if the schedule is strong 2PL-strict
    # set to true when the transaction unlocks the first lock, shared or excl.
    has_unlocked = {tx: False for tx in transactions}
    # set to false if any transaction unlocks any lock but after performs another action
    is_strong_strict = True

    # output list storing lock/unlock actions.
    # for every transaction i in the schedule, execute locks[i] before schedule[i]
    # +1 to add unlocks actions at the end
    locks = [[] for i in range(len(schedule)+1)]

    def lock(target, trans, obj):
        """
        Returns an action object representing the lock action 'target' on 'obj' by 'trans'
        """
        if target != 'SHARED_LOCK' and target != 'XCLUSIVE_L' and target != 'UNLOCKED':
            raise ValueError('Invalid lock/unlock action')
        return Action(target, trans, obj)

    def merge_locks(locks, schedule):
        """
        Returns schedule obtained merging 'schedule' with 'locks'.
        locks is a list of list, is defined as:
                for every transaction i in the schedule, execute locks inside locks[i] before schedule[i]
        """
        sol = []
        for locks_i, op in zip(locks, schedule):
            sol.extend(locks_i + [op])
        sol.extend(locks[len(schedule)])  # add final unlocks
        return sol

    def toState(target, trans, obj, i):
        """
        Takes care of transitioning 'obj' of 'trans' to state 'target', adding the corresponding
        lock or unlock action to the solution list and checking whether the change of state is legal and feasible
        """
        if target != 'START' and target != 'SHARED_LOCK' and target != 'XCLUSIVE_L' and target != 'UNLOCKED':
            raise ValueError('Bad target state')

        # If the user requested to use only excl. locks then use excl locks instead of shared ones
        if use_xl_only and target == 'SHARED_LOCK':
            target = 'XCLUSIVE_L'

        if states[trans][obj] == target:  # already in target state, do nothing
            return

        if target == 'SHARED_LOCK':
            # Before gathering shared lock on 'obj', I've to unlock other transactions
            # that have 'obj' in exclusive lock
            while True:  # need to update to_unlock every time in case of side effects of unlock
                to_unlock = getTransactionsByState('XCLUSIVE_L', obj)
                to_unlock.discard(trans)  # don't unlock myself
                if len(to_unlock) == 0:
                    break
                err = unlock(to_unlock.pop(), obj, i)
                if err:
                    return err  # if here, unfeasible

        if target == 'XCLUSIVE_L':
            # Before gathering exlcusive lock on 'obj', I've to unlock other transactions
            # that have 'obj' in shared or exclusive lock
            while True:  # need to update to_unlock every time in case of side effects of unlock
                to_unlock_xl = getTransactionsByState('XCLUSIVE_L', obj)
                to_unlock_sl = getTransactionsByState('SHARED_LOCK', obj)
                to_unlock = set.union(to_unlock_xl, to_unlock_sl)
                to_unlock.discard(trans)  # don't unlock myself
                if len(to_unlock) == 0:
                    break
                err = unlock(to_unlock.pop(), obj, i)
                if err:
                    return err  # if here, unfeasible

        if transaction_state[trans] == 'SHRINKING' and target != 'UNLOCKED':
            return unfeasible('while processing '+str(schedule[i])+', tansaction '+trans+' has to acquire a lock, ' +
                              'but it has already performed an unlock action.', i)

        if target == 'UNLOCKED':
            transaction_state[trans] = 'SHRINKING'

        # strictness: check if the schedule unlocks an exclusive lock
        if states[trans][obj] == 'XCLUSIVE_L' and target == 'UNLOCKED':
            has_x_unlocked[trans] = True

        # strong strictness: check if the schedule unlocks any lock
        if (states[trans][obj] == 'XCLUSIVE_L' or states[trans][obj] == 'SHARED_LOCK') and target == 'UNLOCKED':
            has_unlocked[trans] = True

        states[trans][obj] = target  # set target state
        # add the (un)lock action to the solution
        locks[i].append(lock(target, trans, obj))

    def unlock(trans, obj, i):
        """ Unlock 'obj' for transaction 'trans'.
        Before unlocking it, it must acquire ALL future locks that it
        will need in the future, because once something gets unlocked, 'trans' can no longer acquire
        locks. So it will look in the future actions of 'trans', searching for read
        and write actions on any object: on the matching objects, it will acquire an 
        exclusive lock if 'trans' performs at least one write action, or, if there are only
        reads, a shared lock. After acquiring those locks finally the lock on 'obj' is released.
        """
        if states[trans][obj] == 'UNLOCKED' or states[trans][obj] == 'START':
            return

        will_be_read = set()
        will_be_written = set()

        # look in the future transactions of 'trans', starting from transaction at 'i'+1
        # for j in range(i+1, len(schedule)):
        # action = schedule[j]
        for action in schedule[i+1:]:
            if action.id_transaction != trans:  # we only need transactions of 'trans'
                continue
            if action.action_type == 'READ':
                will_be_read.add(action.object)
            elif action.action_type == 'WRITE':
                will_be_written.add(action.object)
            else:
                raise ValueError

        for obj_to_lock in will_be_written:
            err = toState('XCLUSIVE_L', trans, obj_to_lock, i)
            if err:
                return err

        # if the object will be read and written I have already placed an exlcusive lock on it
        for obj_to_lock in (will_be_read - will_be_written):
            err = toState('SHARED_LOCK', trans, obj_to_lock, i)
            if err:
                return err

        # Now that I have finally acquired all locks that I will need in the future,
        # 'trans' can unlock 'obj'.
        toState('UNLOCKED', trans, obj, i)

    # - - -  utlis  - - -

    def getTransactionsByState(state, obj):
        """
        returns the set of transactions having object 'obj' in state 'state'
        """
        trans = filter(lambda tx: states[tx][obj] == state, transactions)
        return set(trans)

    def put_final_unlocks():
        """
        Unlocks the all the resources in use at the end of the schedule
        """
        for trans, obj in itertools.product(transactions, objects):
            state = states[trans][obj]
            if state == 'SHARED_LOCK' or state == 'XCLUSIVE_L':
                toState('UNLOCKED', trans, obj, len(schedule))

    def unfeasible(details, i):
        s = 'The schedule is not in 2PL'
        if details is None:
            s += '!'
        else:
            s += ': '+details

        s1 = '\nPartial lock sequence: '
        if not i is None:
            sol = merge_locks(locks, schedule)
            offset = i + sum(map(lambda x: len(x), locks))
            s1 += formatSchedule(sol[:offset])

        return {'sol': None, 'partial_locks': s1, 'err': s}

    # - - - -  main  - - - -

    for i in range(len(schedule)):
        action = schedule[i]

        obj_state = states[action.id_transaction][action.object]

        # If a tx has unlocked an exclusive lock and executes another action, then the whole schedule is not strict
        if has_x_unlocked[action.id_transaction]:
            is_strict = False

        # If a tx has unlocked any lock and executes another action, then the whole schedule is not strong strict
        if has_unlocked[action.id_transaction]:
            is_strong_strict = False

        if action.action_type == 'READ':

            if obj_state == 'START':
                err = toState(
                    'SHARED_LOCK', action.id_transaction, action.object, i)
                if err:
                    return err

            elif obj_state == 'SHARED_LOCK':  # ok, can continue to read
                pass

            elif obj_state == 'XCLUSIVE_L':  # ok, can continue to read
                pass

            elif obj_state == 'UNLOCKED':
                return unfeasible('action '+str(action)+' needs to lock an unlocked object', i)

            else:
                raise ValueError('Bad state')

        elif action.action_type == 'WRITE':

            if obj_state == 'START' or obj_state == 'SHARED_LOCK':
                err = toState('XCLUSIVE_L', action.id_transaction,
                              action.object, i)
                if err:
                    return err

            elif obj_state == 'XCLUSIVE_L':  # ok, can continue to write
                pass

            elif obj_state == 'UNLOCKED':
                return unfeasible('action '+str(action)+' needs to lock an unlocked object', i)

            else:
                raise ValueError('Bad state')

        else:
            raise ValueError('Bad action type')

    put_final_unlocks()  # unlock active locks
    # merge locks and the schedule
    solved_schedule = merge_locks(locks, schedule)

    solved_schedule_str = formatSchedule(solved_schedule)

    return {
        'sol': solved_schedule_str,
        'strict': str(is_strict),
        'strong': str(is_strong_strict)
    }