# MAS Project
pygame+spade Battle Simulator

Simulates an automatic battle using Spade agents.


This simulation features 2 armies fighting for control over a batallion. The point is for the leaders of the army to guide their soldiers to victory. For that, everyone on any team must collaborate

All characters in the game have an agent each for communication.

The troops listen for the commands of the higher ups if they are in range to hear the commands. each features a command stack such that the higher ups can make longer plans.

The commands are as follows:
	- go to - orders surrounding troops to go to a set location
	- wait # seconds - orders surrounding troops to wait
	- wait for a signal - orders troops to wait until an activation signal
	- "NOW!" - signal that makes troops skip their wait commands

The commands are given in a queue by the leaders to syncronize their manpower.

Each troop, in lack of commands from leadership will roam the map and try to survive, hitting enemies if they have enough hp, resting if they are tired, and running away to save their life if they have low hp and meet an enemy. Over-exhaustion deals damage to the troops and resting after regaining all stamina heals them. The leaders extend this troop idle behaviour. Leaders can also follow commands when given by someone with a higher grade than them.

The terrain is loaded from the map.txt file.