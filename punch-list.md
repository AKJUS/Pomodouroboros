
# quick punch list

## some of this should move to github issues

 - implement quick-intention-set button
   - [x] actually hook up hotkey that the instruction text says you should press!!
   - [x] display an error when it isn't time to set an intention / start a
         pomodoro yet (i.e.: on break, etc)
   - [ ] display time of upcoming pomodoro / streak length in title above
         buttons somewhere
   - [x] visibly explain what this dialog is going to do (“Choose an intention
         to start your next pomodoro:”)
   - [ ] set the background color or something for the top 7 so it's clear
         which ones will show up in the quick-set window?
   - [ ] add configurability to set the global hotkey to something else

 - fix bug: dial resizes incorrectly / doesn't respond to monitor reconfiguration
 - there should be a tab showing the current status, so the status menu item is not required
     - this should show:
       - instructions
          - prerequisite: all setExplanation calls need to live in
            pomodouroboros.common, because they should be consistent
            cross-platform (i.e.: implement currently unused
            describeCurrentState)
       - mini timer
         - maybe just a progress bar rather than another ring?
         - visible indication of length of active session
       - buttons for temporary hiding overlay for some interval of time
       - "start a session now" with interval length selection
         - note: probably want to stop sessions from overlapping
       - visual indication of current streak
         - how long (intervals)
         - how long (time)
         - if we're in a grace period, maybe show some alert, since streak is about to break
         - display upcoming durations to present the rules for pomodoro and break lengths
           - maybe make these editable?
 - visible indication in the intention list, which intention is the one being worked on
 - visible indication in the session list, which one is the active session
   - maybe scroll to it initially
 - actually update 'modified' timestamps on edits to intentions
 - remove 'estimates' from the UI for now, since we don't really need that for 1.0
   - (or make it work, maybe just to record estimates for now?)
 - make the 'history' tab work to actually show intervals
 - switch from one-circle to three-circles view so we can have visibility on session length
 - show the score for the current session (maybe current day?) somewhere!
 - "discreet view" for pair programming etc
 - hook up "sessions on" and "intervals on" date views so they actually affect the UI
 - populate "total score" field on sessions tab
 - "hide timer for" button / status menu item: sometimes we need to avoid the distraction of the timer, share our screen, etc, but we don't want to forget about it forever, because that's how you forget to re-display it.
   - also, "show timer again now" button
 - show some visible indication when 'Start Pomodoro!' is disabled, explaining why you can't click it:
    - intention already complete
    - intention abandoned
    - currently on break
 - show users next upcoming streak time (how long is this pomodoro they're about to commit to?)
 - allow users to select a custom time for a pomodoro interval somehow
 - development / quality of life issue: make `./testme` only build bundle if xib files have changed (follow up from alias build)

 - "undo" - I picked the wrong intention in the pomodoro intention selector
   (especially: hit the wrong number hotkey), let me select another one


linux stuff:
- figure out what KDE's version of this is
            iface="org.gnome.Mutter.DisplayConfig",
            signal="MonitorsChanged",
- figure out what "background task" would be, and a UI interaction similar to "relaunch" that won't create extra processes



DONE:

 - development / quality of life issue: make `./testme` use an alias build
 - display the length of the current pomodoro
 - allow for showing all intentions with no filter, so we can see abandoned / completed ones
 - add a way to start a manual session so I can debug this in off hours
 - maybe done? fix(?) start-prompt bug where we are not seeing a start prompt during a session
 - fix bug: dial flickers at the start of StartPrompt, there's probably a duplicate timer?
 - implement reordering intentions, so quick-intention-set gets the right top 7
