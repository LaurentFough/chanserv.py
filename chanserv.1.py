#!/usr/bin/python
#
# ChanServ helper script for XChat
#
# (c) 2015 Krytarik Raido
#       <krytarik@tuxgarage.com>
#       <https://git.launchpad.net/~krytarik/+git/chanserv.py>
#
# (c) 2006-2013 Dennis Kaarsemaker
#       <dennis@kaarsemaker.net>
#       <https://github.com/seveas/chanserv.py>
#
#################################################################
#
# This script is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# version 3, as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
#############################################################################
#
# The script adds one command to XChat: /cs
# /cs understands the following arguments.
#
# To perform an action:
#
#   o,  op       - Op yourself or someone else (/cs op [channel] [nick])
#   v,  voice    - Voice yourself or someone else (/cs voice [channel] [nick])
#   d,  deop     - Deop yourself or someone else (/cs deop [channel] [nick])
#   dv, devoice  - Devoice yourself or someone else (/cs devoice [channel] [nick])
#   i,  info     - Print user info (/cs info [nick])
#   bs, bans     - List bans for a user or all (/cs bans [channel] [nick])
#   ms, matches  - Lists users matching a mask (/cs matches [channel] <mask>)
#   x,  access   - Get or set access rights for a channel (/cs access [channel] [args])
#
# To op yourself, perform an action, and deop:
#
#   k,  kick     - Kick a user, optionally with comment (/cs kick [channel] <nick> [comment])
#                   (currently the same as 'remove')
#   r,  remove   - Remove a user, optionally with comment (/cs remove [channel] <nick> [comment])
#   b,  ban      - Ban a user (/cs ban [channel] [-nuhfiarx] [-t<mins>] <nick>)
#   kb, kickban  - Ban and kick a user (/cs kickban [channel] [-nuhfiarx] [-t<mins>] <nick> [comment])
#   f,  forward  - Ban a user with a forward (/cs forward [channel] [-nuhfiarx] [-t<mins>] <nick> <channel>)
#   kf, kickfwd, - Kickban a user with a forward (/cs kickfwd [channel] [-nuhfiarx] [-t<mins>] <nick> <channel>)
#   kickforward
#   l,  lart     - Ban and kick a user on all fields
#                   (/cs lart [channel] <nick>; equal to: /cs kickban [channel] -nuhfiarx [-t<mins>] <nick>)
#   q,  mute,    - Mute a user (/cs mute [channel] [-nuhfiarx] [-t<mins>] <nick>)
#       quiet
#   a   akick    - Autokick a user (/cs akick [channel] [-nihf] [-t<mins>] <nick> [comment])
#   u,  unban    - Remove all bans for a user (/cs unban [channel] <nick>)
#   t,  topic    - Get or set channel topic (/cs topic [channel] [topic])
#   m,  mode     - Get or set channel modes (/cs mode [channel] [modes])
#   iv, invite   - Invite yourself or someone else (/cs invite [channel] [nick])
#
# * Bans, forwards and mutes take an extra optional argument that specifies what
#   should be banned: nick, ident, host, full mask, account and/or realname.
#     /cs ban -nah <nick> -- Ban nick, account and host
#     /cs forward -nuhfiarx <nick> <channel> -- Forward all
#
# * These commands also take an extra argument to specify
#   when bans/mutes should be lifted automatically.
#     /cs ban -t10 <nick> -- Ban nick for 10 minutes
#     /cs ban -nah -t60 <nick> -- Ban nick, account and host for an hour
#
# * Unban will remove all bans matching the nick or mask.
#   you give as argument (*  and ? wildcards work)

# * It won't actually kick, but use the /remove command.
#
# * The following additional features are implemented:
#    - Auto-rejoin for /remove
#    - Auto-unban
#    - Auto-unmute
#    - Auto-invite
#    - Auto-getkey

__module_name__        = 'ChanServ'
__module_version__     = '3.3.0'
__module_description__ = 'ChanServ helper'

import collections
import xchat
import time
import re

# Event queue
pending = []
# Whois cache
users = {}
resolving_users = []
# Ban cache
bans = collections.defaultdict(list)
quiets = collections.defaultdict(list)
akicks = collections.defaultdict(list)
collecting_bans = []
current_akick = None
# Who cache
whos = {}
collecting_whos = []
# Access rights
can_do_akick = []
can_do_topic = []
collecting_access = []

kick_message = 'Goodbye'
akick_message = ''

atheme_networks = ['freenode']
remove_networks = ['freenode']
quiet_networks = ['freenode', 'oftc']

commands = {'k': 'kick', 'r': 'remove', 'b': 'ban', 'kb': 'kickban',
            'f': 'forward', 'kf': 'kickforward', 'kickfwd': 'kickforward',
            'l': 'lart', 'a': 'akick', 'q': 'quiet', 'mute': 'quiet',
            'u': 'unban', 'o': 'op', 'd': 'deop', 'v': 'voice', 'dv': 'devoice',
            'i': 'info', 'bs': 'bans', 'ms': 'matches', 'x': 'access',
            't': 'topic', 'm': 'mode', 'iv': 'invite'}
op_commands = ['op', 'deop', 'voice', 'devoice']
kick_commands = ['kick', 'remove', 'kickban', 'kickforward', 'lart']
ban_commands = ['ban', 'kickban', 'forward', 'kickforward', 'lart', 'akick', 'quiet']
forward_commands = ['forward', 'kickforward']

def cs(word, word_eol, userdata):
    """Main command dispatcher"""
    if len(word) == 1:
        print("No command specified.")
        return xchat.EAT_ALL

    # Reset on every run
    del pending[:]
    del resolving_users[:]
    del collecting_bans[:]
    del collecting_whos[:]

    command = word[1].lower()

    if command in list(commands.keys()):
        command = commands[command]
    elif command not in list(commands.values()):
        return xchat.EAT_NONE

    server = xchat.get_info('server')
    network = server.split('.')[-2]

    # Get channel
    if command != 'info':
        if len(word) > 2 and word[2][0] in '#&':
            channel_spec = True
            channel = word[2]
            args = word[3:]
        else:
            channel_spec = False
            channel = xchat.get_info('channel')
            args = word[2:]
        if not channel or channel.lower() == network:
            print("No target channel.")
            return xchat.EAT_ALL
        elif not re.match(r'^[#&][^ ,\a]{1,49}$', channel):
            print("Invalid channel: '%s'" % channel)
            return xchat.EAT_ALL
    else:
        if len(word) > 2:
            channel_spec = True
            channel = word[2]
            args = word[2:]
        else:
            channel_spec = False
            channel = xchat.get_info('channel')
            args = [channel]
        if not channel or channel.lower() == network:
            print("No target nick.")
            return xchat.EAT_ALL

    # Get context
    if not channel_spec:
        context = xchat.get_context()
    else:
        context = None
        for chan in xchat.get_list('channels'):
            if channel == chan.channel and server == chan.server:
                context = chan.context
                break
        if not context:
            context = xchat.get_context()

    action = Action(channel = channel, server = server, network = network,
                    me = xchat.get_info('nick'), context = context)

    # Check for options
    if command != 'mode':
        for arg in args[:]:
            if arg.startswith('-'):
                if re.match(r'^-[nuhfiarx]+$', arg):
                    action.bans += arg[1:]
                elif re.match(r'^-t[0-9]+$', arg):
                    action.timer = int(arg[2:])
                args.remove(arg)
            else:
                break

    # Get target
    if args and command not in ('access', 'topic', 'mode'):
        action.target = args[0]
        if re.match(r'^[a-zA-Z_^`|\\[\]{}][-a-zA-Z0-9_^`|\\[\]{}]{0,16}$', action.target):
            action.target_nick = action.target
            action.target_nickm = action.target_nick.lower()
            if command in ban_commands or command in ('unban', 'info', 'bans'):
                action.needs_resolved = True
            elif command == 'matches':
                print("Invalid target: '%s'" % action.target)
                return xchat.EAT_ALL
        elif command in ban_commands or command in ('unban', 'info', 'bans', 'matches'):
            targeto = action.target
            if '$' in action.target[1:]:
                action.target, action.forward_to = action.target.rsplit('$', 1)
            if re.match(r'^([^$][^ ]*![^ ]+@[^ ]+|\$x:[^ ]+)$', action.target):
                action.bans = 'f'
                action.target_mask = action.target
                action.target_maskm = action.target_mask
                match = re.findall(r'^(?:\$x:|)([^ ]+)!([^ ]+)@([^ ]+?)(?:#([^ ]+)|)$', action.target_mask)
                if match:
                    action.target_nick, action.target_ident, action.target_host, action.target_name = match[0]
                    action.target_identm = get_identm(action.target_ident)
                    action.target_name_bannable = action.target_name
                    action.target_ipaddr, action.target_ipaddrm = get_ipaddr(action.target_host)
            elif re.match(r'^\$a:[^ ]+$', action.target):
                action.bans = 'f'
                action.target_mask = action.target
                action.target_maskm = action.target_mask
                action.target_account = action.target[3:]
            elif re.match(r'^\$r:[^ ]+$', action.target):
                action.bans = 'f'
                action.target_mask = action.target
                action.target_maskm = action.target_mask
                action.target_name = action.target[3:]
                action.target_name_bannable = action.target_name
            elif re.match(r'^\$(j:[^ ]+|~a)$', action.target):
                action.bans = 'f'
                action.target_mask = action.target
                action.target_maskm = action.target_mask
            else:
                print("Invalid target: '%s'" % targeto)
                return xchat.EAT_ALL
            xchat.emit_print('Server Text', '\x02%s\x02 (a: %s, r: %s)' %
                (action.target_mask, action.target_account, action.target_name))
        else:
            print("Invalid target: '%s'" % action.target)
            return xchat.EAT_ALL

    # Non-ban operations
    if command in op_commands:
        action.needs_op = False
        if not action.target_nick:
            action.target_nick = action.me
        action.actions.append('ChanServ %s %%(channel)s %%(target_nick)s' % command)

    elif command == 'info':
        action.needs_op = False

    elif command == 'bans':
        action.do_bans = True
        action.needs_op = False

    elif command == 'matches':
        action.do_matches = True
        action.needs_op = False

    elif command == 'access':
        action.needs_op = False
        if not args:
            action.actions.append('ChanServ access %(channel)s list')
        else:
            action.actions.append('ChanServ access %%(channel)s %s' % ' '.join(args))

    elif command == 'topic':
        if not args:
            action.needs_op = False
            action.actions.append('topic %(channel)s')
        elif action.channel in can_do_topic:
            action.needs_op = False
            action.actions.append('ChanServ topic %%(channel)s %s' % ' '.join(args))
        else:
            action.actions.append('topic %%(channel)s %s' % ' '.join(args))

    elif command == 'mode':
        if not args:
            action.needs_op = False
            action.actions.append('mode %(channel)s')
        else:
            if re.match(r'^\+?[bq]+$', ' '.join(args)):
                action.needs_op = False
            action.actions.append('mode %%(channel)s %s' % ' '.join(args))

    elif command == 'invite':
        if not action.target_nick:
            action.needs_op = False
            action.actions.append('ChanServ invite %(channel)s')
        else:
            action.actions.append('invite %(target_nick)s %(channel)s')

    # Usage check
    elif not args or (command in forward_commands and (len(args) < 2 and not action.forward_to)):
        print("Not enough arguments for '%s'" % command)
        return xchat.EAT_ALL

    # Ban operations
    if command in ban_commands:
        action.do_ban = True

        if not action.bans:
            if command == 'lart':
                action.bans = 'nuhfiarx'
            else:
                action.bans = 'h'

        # Get forward channel
        if command in forward_commands or action.forward_to:
            if not action.forward_to:
                action.forward_to = '$' + args[1]
            else:
                action.forward_to = '$' + action.forward_to
            if not re.match(r'^[#&][^ ,\a]{1,49}$', action.forward_to[1:]):
                print("Invalid channel: '%s'" % action.forward_to[1:])
                return xchat.EAT_ALL

        elif command == 'quiet':
            if action.network in quiet_networks:
                action.banmode = 'q'
            else:
                print("Network does not support quiets.")

        elif command == 'akick':
            if action.channel in can_do_akick:
                action.do_akick = True
            elif action.network not in atheme_networks:
                print("Network does not support AKICK.")
            else:
                print("Insufficient access rights for AKICK.")

        elif action.timer and action.channel in can_do_akick \
                and not (action.bans == 'f' and action.target_mask.startswith('$')):
            action.do_akick = True

        # Schedule bans
        if not action.do_akick:
            if 'f' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s %(target_maskm)s%(forward_to)s')
            if 'n' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s %(target_nick)s!*@*%(forward_to)s')
            if 'u' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s *!%(target_identm)s@*%(forward_to)s')
            if 'h' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s *!*@%(target_host)s%(forward_to)s')
            if 'i' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s *!*@%(target_ipaddrm)s%(forward_to)s')
            if 'a' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $a:%(target_account)s%(forward_to)s')
            if 'r' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $r:%(target_name_bannable)s%(forward_to)s')
            if 'x' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $x:%(target_nick)s!%(target_identm)s@%(target_host)s#%(target_name_bannable)s%(forward_to)s')

        # Schedule AKICKs
        else:
            action.reason = ' '.join(args[1:]) or akick_message
            if action.timer:
                action.akick_opts = '!t %d' % action.timer
            if 'f' in action.bans:
                action.actions.append('ChanServ akick %(channel)s add %(target_maskm)s %(akick_opts)s %(reason)s')
            if 'n' in action.bans:
                action.actions.append('ChanServ akick %(channel)s add %(target_nick)s!*@* %(akick_opts)s %(reason)s')
            if 'u' in action.bans:
                action.actions.append('ChanServ akick %(channel)s add *!%(target_identm)s@* %(akick_opts)s %(reason)s')
            if 'h' in action.bans:
                action.actions.append('ChanServ akick %(channel)s add *!*@%(target_host)s %(akick_opts)s %(reason)s')
            if 'i' in action.bans:
                action.actions.append('ChanServ akick %(channel)s add *!*@%(target_ipaddrm)s %(akick_opts)s %(reason)s')
            if 'a' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $a:%(target_account)s')
            if 'r' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $r:%(target_name_bannable)s')
            if 'x' in action.bans:
                action.actions.append('mode %(channel)s +%(banmode)s $x:%(target_nick)s!%(target_identm)s@%(target_host)s#%(target_name_bannable)s')

    # Unban
    elif command == 'unban':
        action.do_unban = True

    # Schedule kick
    if command in kick_commands:
        action.reason = ' '.join(args[1:]) or kick_message
        if action.network in remove_networks:
            action.actions.append('remove %(channel)s %(target_nick)s %(reason)s')
        else:
            action.actions.append('kick %(channel)s %(target_nick)s %(reason)s')

    return action.schedule()

class Action(object):
    """A list of actions to do, and information needed for them"""
    def __init__(self, channel, server, network, me, context):
        self.channel = channel
        self.server = server
        self.network = network
        self.me = me
        self.me_curr = me
        self.context = context
        self.stamp = time.time()

        # Check existing bans first
        self.check_bans = True

        # Defaults
        self.am_op = False
        self.deop = False
        self.needs_op = True
        self.do_ban = False
        self.do_unban = False
        self.do_bans = False
        self.do_matches = False
        self.do_akick = False
        self.needs_resolved = False
        self.resolved = False
        self.bans_parsed = False
        self.whos_parsed = False
        self.target = ''
        self.target_nick = None
        self.target_nickm = None
        self.target_ident = None
        self.target_identm = None
        self.target_host = None
        self.target_mask = None
        self.target_maskm = None
        self.target_account = None
        self.target_name = None
        self.target_name_bannable = None
        self.target_ipaddr = None
        self.target_ipaddrm = None
        self.banmode = 'b'
        self.forward_to = ''
        self.reason = ''
        self.bans = ''
        self.timer = None
        self.akick_opts = ''
        self.actions = []

    def __str__(self):
        ctx = {'channel': self.channel, 'target': self.target}
        if hasattr(self, 'target_ident'):
            ctx['target'] = '%s (a: %s, r: %s)' % (self.target_mask, self.target_account, self.target_name)
        ctx['actions'] = ' | '.join(self.actions)
        return 'C: %(channel)s T: %(target)s A: %(actions)s' % ctx

    def schedule(self, update_stamp=False):
        """Request information and add ourselves to the queue"""
        if update_stamp:
            self.stamp = time.time()

        if self.do_unban or self.do_bans or (self.do_ban and self.check_bans):
            collecting_bans.append(self.channel)
        elif self.do_matches:
            collecting_whos.append(self.channel)

        pending.append(self)
        run_pending()
        return xchat.EAT_ALL

    def resolve_nick(self):
        """Try to find nick, ident and host"""
        if self.target_nickm in users:
            if users[self.target_nickm].time < time.time() - 10:
                del users[self.target_nickm]
                resolving_users.append(self.target_nickm)
                self.context.command('whois %s' % self.target_nickm)
            else:
                self.target_ident = users[self.target_nickm].ident
                self.target_identm = get_identm(self.target_ident)
                self.target_host = users[self.target_nickm].host
                self.target_mask = '%s!%s@%s' % (self.target_nick, self.target_ident, self.target_host)
                self.target_maskm = '%s!%s@%s' % (self.target_nick, self.target_identm, self.target_host)
                self.target_account = users[self.target_nickm].account
                self.target_name = users[self.target_nickm].name
                self.target_name_bannable = self.target_name.replace(r' ', '?')
                self.target_ipaddr, self.target_ipaddrm = get_ipaddr(self.target_host)
                self.resolved = True

                xchat.emit_print('Server Text', '\x02%s\x02 (a: %s, r: %s)' %
                    (self.target_mask, self.target_account, self.target_name))

                if self.do_ban:
                    # For gateway users, use different defaults
                    if self.bans == 'h' and re.match('^(gateway/(shell|web)|conference|nat)/', self.target_host):
                        if re.match(r'^gateway/web/freenode/', self.target_host):
                            ban_mask = '*!*@%s' % self.target_ipaddr
                        else:
                            gateway = re.match(r'^((gateway/shell|conference|nat)/.+/|gateway/web/)', self.target_host)
                            ban_mask = '*!%%(target_identm)s@%s*' % gateway.group(1)
                        if not self.do_akick:
                            self.actions.insert(self.actions.index(
                                'mode %(channel)s +%(banmode)s *!*@%(target_host)s%(forward_to)s'),
                                'mode %%(channel)s +%%(banmode)s %s%%(forward_to)s' % ban_mask)
                            self.actions.remove('mode %(channel)s +%(banmode)s *!*@%(target_host)s%(forward_to)s')
                        else:
                            self.actions.insert(self.actions.index(
                                'ChanServ akick %(channel)s add *!*@%(target_host)s %(akick_opts)s %(reason)s'),
                                'ChanServ akick %%(channel)s add %s %%(akick_opts)s %%(reason)s' % ban_mask)
                            self.actions.remove('ChanServ akick %(channel)s add *!*@%(target_host)s %(akick_opts)s %(reason)s')
                    # Don't try IP address ban if none found
                    if 'i' in self.bans and not self.target_ipaddrm:
                        if not self.do_akick:
                            self.actions.remove('mode %(channel)s +%(banmode)s *!*@%(target_ipaddrm)s%(forward_to)s')
                        else:
                            self.actions.remove('ChanServ akick %(channel)s add *!*@%(target_ipaddrm)s %(akick_opts)s %(reason)s')
                        xchat.emit_print('Server Error', "Cannot do an IP address ban for '%s', none found." % self.target_nick)
                    # Don't try account ban if not identified
                    if 'a' in self.bans and not self.target_account:
                        self.actions.remove('mode %(channel)s +%(banmode)s $a:%(target_account)s%(forward_to)s')
                        xchat.emit_print('Server Error', "Cannot do an account ban for '%s', not identified." % self.target_nick)

                run_pending()
        else:
            resolving_users.append(self.target_nickm)
            self.context.command('whois %s' % self.target_nickm)

    def fetch_bans(self):
        """Read bans for a channel"""
        bans[self.channel] = []
        quiets[self.channel] = []
        akicks[self.channel] = []
        if self.network in quiet_networks:
            self.context.command('mode %s +qb' % self.channel)
        else:
            self.context.command('mode %s +b' % self.channel)
        if self.channel in can_do_akick:
            self.context.command('ChanServ akick %s list' % self.channel)

    def parse_bans(self):
        """Check bans and schedule unbans"""
        if self.do_ban and self.check_bans:
            kwargs = dict(list(self.__dict__.items()))

            for action in self.actions[:]:
                action_res = action % kwargs
                action_split = action_res.split()

                if action_split[0] == 'mode':
                    if action_split[2] == '+q':
                        for quiet in quiets[self.channel]:
                            if quiet[0][1:].rsplit('$', 1)[0] == action_split[3][1:].rsplit('$', 1)[0]:
                                self.actions.remove(action)
                                xchat.emit_print('Server Error', '\x02%s\x02 is already on quiet list.' % quiet[0])

                    elif action_split[2] == '+b':
                        for ban in bans[self.channel]:
                            if ban[0][1:].rsplit('$', 1)[0] == action_split[3][1:].rsplit('$', 1)[0]:
                                self.actions.remove(action)
                                xchat.emit_print('Server Error', '\x02%s\x02 is already on ban list.' % ban[0])

                elif action.startswith('ChanServ akick'):
                    for akick in akicks[self.channel]:
                        if akick[0] == action_split[4]:
                            self.actions.remove(action)
                            xchat.emit_print('Server Error', '\x02%s\x02 is already on AKICK list.' % akick[0])

        elif self.do_unban or self.do_bans:
            bans_fnd = False

            if not self.target:
                xchat.emit_print('Server Text', 'Channel: \x02%s\x02' % self.channel)

            for quiet in quiets[self.channel]:
                if not self.target or self.match(quiet[0], self):
                    bans_fnd = True
                    if self.do_bans:
                        xchat.emit_print('Server Text', 'Quiet: \x02%s\x02 [setter: %s, date: %s]' % (quiet[0], quiet[1], quiet[2][4:]))
                    else:
                        self.actions.append('mode %s -q %s' % (self.channel, quiet[0]))

            for ban in bans[self.channel]:
                if not self.target or self.match(ban[0], self):
                    bans_fnd = True
                    if self.do_bans:
                        xchat.emit_print('Server Text', 'Ban: \x02%s\x02 [setter: %s, date: %s]' % (ban[0], ban[1], ban[2][4:]))
                    else:
                        self.actions.append('mode %s -b %s' % (self.channel, ban[0]))

            for akick in akicks[self.channel]:
                if not self.target or self.match(akick[0], self):
                    bans_fnd = True
                    if self.do_bans:
                        xchat.emit_print('Server Text', 'AKICK: %s' % akick[1])
                    else:
                        self.actions.append('ChanServ akick %s del %s' % (self.channel, akick[0]))

            if not bans_fnd:
                if not self.target:
                    xchat.emit_print('Server Text', '\x02No bans for this channel.\x02')
                else:
                    xchat.emit_print('Server Text', '\x02No matching bans for this user.\x02')

        self.bans_parsed = True
        run_pending()

    def fetch_whos(self):
        """Read whos for a channel"""
        whos[self.channel] = []
        self.context.command('who %s %%cnuhar' % self.channel)

    def parse_whos(self):
        """Check whos for matches"""
        if self.do_matches:
            matches, nicks = [], ''

            for who in whos[self.channel]:
                if self.match(self.target_mask, who):
                    matches.append(who.target_nick)

            if matches:
                match_cnt = len(matches)
                if match_cnt <= 12:
                    nicks = ', '.join(sorted(matches))
                else:
                    nicks = ', '.join(sorted(matches)[:11]) + ', ...'
                xchat.emit_print('Server Text', '\x02Matches %s user%s\x02: %s' % (match_cnt, 's' if match_cnt > 1 else '', nicks))
            else:
                xchat.emit_print('Server Text', '\x02No matches for this mask.\x02')

        self.whos_parsed = True
        run_pending()

    def get_prefix(self):
        if self.channel == self.context.get_info('channel'):
            self.me_curr = self.context.get_info('nick')
            for user in self.context.get_list('users'):
                if user.nick == self.me_curr:
                    return user.prefix
            return ''
        return ''

    def run(self):
        """Perform all registered actions"""
        kwargs = dict(list(self.__dict__.items()))

        for action in self.actions[:]:
            if action.startswith('ChanServ op') and self.am_op:
                action = 'mode %(channel)s +o %(target_nick)s'
            elif action.startswith('ChanServ deop') and self.am_op:
                action = 'mode %(channel)s -o %(target_nick)s'
            elif action.startswith('ChanServ voice') and self.am_op:
                action = 'mode %(channel)s +v %(target_nick)s'
            elif action.startswith('ChanServ devoice') and self.am_op:
                action = 'mode %(channel)s -v %(target_nick)s'

            action_res = action % kwargs
            self.context.command(action_res)
            if action.startswith('ChanServ akick'):
                self.actions.remove(action)

        self.done()

    def done(self):
        """Finalization and cleanup"""
        if self in pending:
            pending.remove(self)

        # Deop?
        if self.deop:
            self.context.command('mode %s -o %s' % (self.channel, self.me_curr))
            self.deop = False

        # Schedule removal?
        if self.do_ban and self.timer and self.actions:
            self.actions = [a.replace('+%(banmode)s', '-%(banmode)s') for a in self.actions]
            xchat.hook_timer(self.timer * 60000, lambda act: act.schedule(update_stamp=True) and False, self)
            self.timer = 0

    def match(self, ban, action):
        """Does a ban match this action"""
        if re.match(r'^[^$][^ ]*![^ ]+@[^ ]+$', ban):
            result = re.compile('^' + re.escape(ban.rsplit('$', 1)[0]).replace(r'\*', '.*').replace(r'\?', '.').replace(r'!\~', '!\~?') + '$').match('%s!%s@%s' %
                (action.target_nick, action.target_ident, action.target_host))
            if not result and action.target_ipaddr:
                result = re.compile('^' + re.escape(ban.rsplit('$', 1)[0]).replace(r'\*', '.*').replace(r'\?', '.').replace(r'!\~', '!\~?') + '$').match('%s!%s@%s' %
                    (action.target_nick, action.target_ident, action.target_ipaddr))
            return result
        elif re.match(r'^\$a:[^ ]+$', ban):
            if action.target_account:
                return re.compile('^' + re.escape(ban[3:].rsplit('$', 1)[0]).replace(r'\*', '.*').replace(r'\?', '.') + '$').match(self.target_account)
        elif re.match(r'^\$r:[^ ]+$', ban):
            if action.target_name:
                return re.compile('^' + re.escape(ban[3:].rsplit('$', 1)[0]).replace(r'\*', '.*').replace(r'\?', '.') + '$').match(self.target_name)
        elif re.match(r'^\$x:[^ ]+$', ban):
            return re.compile('^' + re.escape(ban[3:].rsplit('$', 1)[0]).replace(r'\*', '.*').replace(r'\?', '.').replace(r'!\~', '!\~?') + '$').match('%s!%s@%s#%s' %
                (action.target_nick, action.target_ident, action.target_host, action.target_name))
        elif re.match(r'^\$j:[^ ]+$', ban):
            return 1
        elif re.match(r'^\$~a$', ban):
            if not action.target_account:
                return 1

def get_identm(target_ident):
    if target_ident.startswith('~'):
        return target_ident.replace('~', '*', 1)
    elif len(target_ident) <= 9:
        return '*%s' % target_ident
    else:
        return target_ident

def get_ipaddr(target_host):
    ipaddr = re.match(r'.*?(([0-9]{1,3}[.-]){3}[0-9]{1,3})', target_host)
    if ipaddr:
        return [ipaddr.group(1).replace(r'-', '.')] * 2
    if re.match(r'^([0-9a-f]{0,4}:)+([0-9a-f]{1,4})?$', target_host, re.I):
        return (target_host, shorten_ipv6(target_host))
    ipaddr = re.match(r'.*?([0-9a-f]{32})', target_host, re.I)
    if ipaddr:
        ipaddr = ':'.join(re.findall(r'....', ipaddr.group(1).lower()))
        ipaddr = re.sub(r'(^|:)0+([^:]+)', r'\1\2', ipaddr)
        ipaddr = re.sub(r'(^|:)(0(:|$)){2,}', '::', ipaddr, count=1)
        return (ipaddr, shorten_ipv6(ipaddr))
    return [None] * 2

def shorten_ipv6(ipaddr):
    ipsegs = re.match(r'^(.*)::(.*)$', ipaddr)
    if ipsegs:
        ipaddr = ':'.join([x for x in [ipsegs.group(1)] +
            ["0"] * (8 - len(re.findall(r'([^:]+)', ipaddr))) + [ipsegs.group(2)] if x])
    ipaddr = re.sub(r'(:[^:]{1,4}){4}$', ':*', ipaddr, count=1)
    return re.sub(r'(^|:)(0(:|$)){2,}', '::', ipaddr, count=1)

def run_pending(me_curr=None, just_opped=None):
    """Check all actions and run them if all information is there"""
    can_run = False

    for p in pending:
        # Find needed information
        if p.needs_resolved and not p.resolved:
            can_run = False
            p.resolve_nick()
        else:
            can_run = True

        if can_run and (p.do_unban or p.do_bans or (p.do_ban and p.check_bans and p.actions)):
            if p.channel in collecting_bans:
                can_run = False
                p.fetch_bans()
            elif not p.bans_parsed:
                can_run = False
                p.parse_bans()
            else:
                can_run = True

        elif can_run and p.do_matches:
            if p.channel in collecting_whos:
                can_run = False
                p.fetch_whos()
            elif not p.whos_parsed:
                can_run = False
                p.parse_whos()
            else:
                can_run = True

        # Got anything to do?
        if can_run and not p.actions:
            p.done()
            continue

        # Am I opped?
        if can_run:
            if p.context == just_opped:
                p.am_op = True
                p.deop = True
                p.me_curr = me_curr
            elif '@' in p.get_prefix():
                p.am_op = True
            else:
                p.am_op = False

            if p.needs_op and not p.am_op:
                can_run = False
                p.context.command('ChanServ op %s' % p.channel)
            else:
                can_run = True

        # Timeout?
        if can_run and p.stamp < time.time() - 10:
            xchat.emit_print('Server Error', 'Operation timed out.')
            p.done()
            continue

        if can_run:
            p.run()

# Data processing
def do_mode(word, word_eol, userdata):
    """Run pending actions when ChanServ opped us"""
    if pending:
        context = xchat.get_context()
        me_curr = context.get_info('nick')
        if word[0] == ':ChanServ!ChanServ@services.' and word[3] == '+o' and word[4] == me_curr:
            for p in pending:
                if p.context == context:
                    run_pending(me_curr = me_curr, just_opped = context)
                    break
xchat.hook_server('MODE', do_mode)

class User(object):
    def __init__(self, nick, ident, host, name):
        self.nick = nick
        self.ident = ident
        self.host = host
        self.name = name
        self.account = None
        self.time = time.time()
def do_whois(word, word_eol, userdata):
    """Store Whois replies in global cache"""
    nick = word[3].lower()
    if nick in resolving_users:
        if word[1] in ('311', '314') and nick not in users:
            users[nick] = User(nick = nick, ident = word[4], host = word[5], name = word_eol[7][1:])
        elif word[1] == '330' and not users[nick].account:
            users[nick].account = word[4]
        elif word[1] == '307' and not users[nick].account:
            users[nick].account = word[3]
        return xchat.EAT_ALL
xchat.hook_server('311', do_whois) # User (Whois)
xchat.hook_server('314', do_whois) # User (Whowas)
xchat.hook_server('330', do_whois) # Account
xchat.hook_server('312', do_whois) # Server
xchat.hook_server('313', do_whois) # Operator
xchat.hook_server('317', do_whois) # Idle
xchat.hook_server('301', do_whois) # Away
xchat.hook_server('319', do_whois) # Channels
xchat.hook_server('307', do_whois) # Registered
xchat.hook_server('335', do_whois) # Bot
xchat.hook_server('379', do_whois) # Modes
xchat.hook_server('671', do_whois) # Secure
xchat.hook_server('275', do_whois) # Secure
xchat.hook_server('276', do_whois) # Certificate
xchat.hook_server('378', do_whois) # Host
xchat.hook_server('338', do_whois) # Actually

def do_missing(word, word_eol, userdata):
    """Fall back to Whowas if Whois fails"""
    nick = word[3].lower()
    if nick in resolving_users:
        for p in pending:
            if p.target_nickm == nick:
                p.context.command('whowas %s' % nick)
                return xchat.EAT_ALL
xchat.hook_server('401', do_missing)

def do_endwhois(word, word_eol, userdata):
    """Process the queue after nick resolution"""
    nick = word[3].lower()
    if nick in resolving_users:
        if nick in users:
            resolving_users.remove(nick)
            run_pending()
        return xchat.EAT_ALL
xchat.hook_server('318', do_endwhois) # Whois
xchat.hook_server('369', do_endwhois) # Whowas

def do_endwasno(word, word_eol, userdata):
    """Display error if nick cannot be resolved"""
    nick = word[3].lower()
    if nick in resolving_users:
        for p in pending[:]:
            if p.target_nickm == nick:
                xchat.emit_print('Server Error', "Cannot find '%s'" % p.target_nick)
                pending.remove(p)
                return xchat.EAT_ALL
xchat.hook_server('406', do_endwasno)

def do_ban(word, word_eol, userdata):
    """Process banlists"""
    channel = word[3]
    if channel in collecting_bans:
        ban = [word[4], word[5], time.ctime(float(word[6]))]
        bans[channel].append(ban)
        return xchat.EAT_ALL
xchat.hook_server('367', do_ban)

def do_quiet(word, word_eol, userdata):
    """Process banlists"""
    channel = word[3]
    if channel in collecting_bans:
        ban = [word[-3], word[-2], time.ctime(float(word[-1]))]
        quiets[channel].append(ban)
        return xchat.EAT_ALL
xchat.hook_server('728', do_quiet)
xchat.hook_server('344', do_quiet)

def do_endban(word, word_eol, userdata):
    """Process end-of-ban markers"""
    channel = word[3]
    if channel in collecting_bans:
        if channel not in can_do_akick:
            collecting_bans.remove(channel)
            run_pending()
        return xchat.EAT_ALL
xchat.hook_server('368', do_endban)

def do_endquiet(word, word_eol, userdata):
    """Process end-of-quiet markers"""
    channel = word[3]
    if channel in collecting_bans:
        return xchat.EAT_ALL
xchat.hook_server('729', do_endquiet)
xchat.hook_server('345', do_endquiet)

class Who(object):
    def __init__(self, nick, ident, host, ipaddr, name, account=None):
        self.target_nick = nick
        self.target_ident = ident
        self.target_host = host
        self.target_ipaddr = ipaddr
        self.target_account = account
        self.target_name = name

def do_who(word, word_eol, userdata):
    """Process wholists"""
    channel = word[3]
    if channel in collecting_whos:
        who = Who(nick = word[7], ident = word[4], host = word[5], ipaddr = get_ipaddr(word[5])[0], name = word_eol[10])
        whos[channel].append(who)
        return xchat.EAT_ALL
xchat.hook_server('352', do_who)

def do_whospc(word, word_eol, userdata):
    """Process wholists"""
    channel = word[3]
    if channel in collecting_whos:
        who = Who(nick = word[6], ident = word[4], host = word[5], ipaddr = get_ipaddr(word[5])[0], account = word[7], name = word_eol[8])
        whos[channel].append(who)
        return xchat.EAT_ALL
xchat.hook_server('354', do_whospc)

def do_endwho(word, word_eol, userdata):
    """Process end-of-who markers"""
    channel = word[3]
    if channel in collecting_whos:
        collecting_whos.remove(channel)
        run_pending()
        return xchat.EAT_ALL
xchat.hook_server('315', do_endwho)

def rejoin(word, word_eol, userdata):
    """Rejoin when /remove'd"""
    if word[0][1:word[0].find('!')] == xchat.get_info('nick') and len(word) > 3 and word[3][1:].lower() == 'requested':
        xchat.command('join %s' % word[2])
#xchat.hook_server('PART', rejoin)

def on_invite(word, word_eol, userdata):
    """Autojoin when ChanServ invites us"""
    if word[0] == ':ChanServ!ChanServ@services.':
        xchat.command('join %s' % word[-1][1:])
xchat.hook_server('INVITE', on_invite)

def on_notice(word, word_eol, userdata):
    global current_akick
    # NickServ notices
    if word[0] == ':NickServ!NickServ@services.':
        if re.match(r'^:\+?Access flag\(s\)', word_eol[3]):
            if 'f' in word[5]:
                can_do_akick.append(word[-1])
            if 't' in word[5]:
                can_do_topic.append(word[-1])
            if xchat.get_info('server') in collecting_access:
                return xchat.EAT_ALL
        elif re.match(r'^channel access matches for the nickname', word_eol[4]):
            server = xchat.get_info('server')
            if server in collecting_access:
                collecting_access.remove(server)
                return xchat.EAT_ALL

    # ChanServ notices
    elif word[0] == ':ChanServ!ChanServ@services.':
        if re.match(r'^:\+?Unbanned', word[3]):
            xchat.command('join %s' % word[6][1:-1])
        elif re.match(r'^:\+?Channel [^ ]+ key is:', word_eol[3]):
            xchat.command('join %s %s' % (word[4][1:-1], word[-1]))

        # Yay heuristics. Chances are reasonable that only one channel is in
        # collecting_bans at any time, so let's assume that. Worst that could
        # happen is that non-existing bans are shown or removal of them is tried.
        elif re.match(r'^:\+?AKICK list', word_eol[3]):
            current_akick = word[-1][1:-2]
            if current_akick in collecting_bans:
                return xchat.EAT_ALL
            else:
                current_akick = None

        elif current_akick and '[setter:' in word_eol[0] and 'modified:' in word_eol[0]:
            # This looks like a ban to me. So everybody, just follow me.
            ban = [word[4][1:-1], word_eol[4]]
            akicks[current_akick].append(ban)
            return xchat.EAT_ALL

        elif current_akick and word_eol[9] == 'AKICK list.':
            current_akick = None
            channel = word[-3][1:-3]
            if channel in can_do_akick:
                collecting_bans.remove(channel)
                run_pending()
            return xchat.EAT_ALL

        # Print all other ChanServ notices in current tab
        xchat.emit_print('Notice', 'ChanServ', word_eol[3].lstrip(':+'))
        return xchat.EAT_ALL
xchat.hook_server('NOTICE', on_notice)

def listchans(word=None, word_eol=None, userdata=None):
    if not word:
        server = xchat.get_info('server')
        if not server:
            return xchat.EAT_ALL
    else:
        server = word[0][1:]
    if server.split('.')[-2] in atheme_networks:
        collecting_access.append(server)
        xchat.command('NickServ listchans')
xchat.hook_server('376', listchans)

def loadevent(userdata=None, event='unloaded'):
    print('%s v%s %s' % (__module_name__, __module_version__, event))
xchat.hook_unload(loadevent)

# Fetch channel access
listchans()

# Turn on autorejoin
#xchat.command('set -quiet irc_auto_rejoin ON')

# Unban when muted
xchat.hook_server('404', lambda word, word_eol, userdata: xchat.command('ChanServ unban %s' % word[3]))

# Convince ChanServ to let me in when key/unban/invite is needed
xchat.hook_server('471', lambda word, word_eol, userdata: xchat.command('ChanServ invite %s' % word[3]))
xchat.hook_server('473', lambda word, word_eol, userdata: xchat.command('ChanServ invite %s' % word[3]))
xchat.hook_server('474', lambda word, word_eol, userdata: xchat.command('ChanServ unban %s' % word[3]))
xchat.hook_server('475', lambda word, word_eol, userdata: xchat.command('ChanServ getkey %s' % word[3]))

# Channel operator/privs needed
xchat.hook_server('482', lambda word, word_eol, userdata: xchat.emit_print('Server Error', word_eol[3]))

xchat.hook_command('cs', cs, 'For help with /cs, please read the comments in the script')
loadevent(event='loaded')
