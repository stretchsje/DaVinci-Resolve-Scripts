# DaVinci-Resolve-Scripts
A few scripts that help me get my clips sorted and organized in DaVinci Resolve.

Organize Media Pool Into Days:
This script separates files into Videos, Music, and Picture bins.  The Videos bin will be sorted by day in DDD, MM DD format which I find useful for Resolve's Cut page when using a Source Tape.  It is offset so that a "day" ends at 3am so that clips from 11:59pm and 12:01am are together.  Logically this is a continuation of the same night.  3am is the cutoff.

Set Timecode for Media Pool Clips (GUI):
This script is for organizing files by date.  Resolve ignores the Create and Modified dates on the Cut page and instead looks at StartTC.  Most phones and a lot of cameras do not set this attribute.  This script will go through all of your clips and set the StartTC.  There is a user interface to select which date is used.  Since most phones and cameras embed a datetime into the filename, it can try that first, which is probably most reliable as create and modified dates are sometimes changed when copying files from one disk to another.  It can use the create/modified date as a fallback.  There are options to skip files that already have a timecode (recommended) or those already in use on the timeline (also recommended.)  Updating the StartTC on a clip in use on the timeline will result in it showing as media offline and you will have to relink it.


To use these scripts, copy the file to the following folder depending on OS.

Mac OS:
/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts

Windows:
%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts

Linux: /opt/resolve/Fusion/Scripts (or /home/resolve/Fusion/Scripts/ depending on installation)

To execute the script, open DaVinci Resolve, go to the Workspaces menu, then Scripts.  The scripts should appear there automatically.