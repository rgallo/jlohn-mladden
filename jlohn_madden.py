import text_to_speech
import websocket
import ujson
import pyttsx3
import requests
import time
import random


BLASE_MAP = {
    0: 'first',
    1: 'second',
    2: 'third',
}


def pronounce_inning(inning):
    if inning == 1:
        return 'first'
    if inning == 2:
        return 'second'
    if inning == 3:
        return 'third'
    return '{}th'.format(inning)


class PlayerNames(object):

    def __init__(self):
        self._players = {}

    def get(self, id_):
        if id_ in self._players:
            return self._players[id_]
        try:
            player = requests.get('https://blaseball.com/database/players?ids={}'.format(id_))
        except Exception:
            return None
        name = player.json()[0].get('name')
        if name:
            self._players[id_] = name
        return name


player_names = PlayerNames()


class BlaseballGlame(object):

    def __init__(self):
        self.game_logs = []
        self.id_ = ''
        self.away_team = ''
        self.home_team = ''
        self.at_bat = ''
        self.pitching = ''
        self.inning = 1
        self.top_of_inning = False
        self.batting_change = False
        self.away_score = 0
        self.home_score = 0
        self.strikes = 0
        self.balls = 0
        self.outs = 0
        self.on_blase = ['', '', '']
        self.bases_occupied = 0
        self.team_at_bat = ''

    @property
    def has_runners(self):
        return self.on_blase != ['', '', '']

    @property
    def runners(self):
        runners = []
        for i, player in enumerate(self.on_blase):
            if player:
                runners.append((player, BLASE_MAP[i]))
        return runners

    def update(self, msg):
        """msg should already be json, filtered to the appropriate team"""
        pbp = msg['lastUpdate']
        self.game_logs.append(pbp)

        self.id_ = msg['_id']
        self.away_team = msg['awayTeamName']
        self.home_team = msg['homeTeamName']
        self.away_score = msg['awayScore']
        self.home_score = msg['homeScore']

        self.inning = msg['inning'] + 1
        self.batting_change = msg['topOfInning'] != self.top_of_inning
        self.top_of_inning = msg['topOfInning']  # true means away team at bat

        team_at_bat = msg['awayTeamNickname'] if self.top_of_inning else msg['homeTeamNickname']
        if team_at_bat:
            self.team_at_bat = team_at_bat
        at_bat = msg['awayBatterName'] if self.top_of_inning else msg['homeBatterName']
        pitching = msg['homePitcherName'] if self.top_of_inning else msg['awayPitcherName']
        # sometimes these just clear out, don't overwrite if cached
        self.at_bat = at_bat or self.at_bat
        self.pitching = pitching or self.pitching

        self.strikes = msg['atBatStrikes']
        self.balls = msg['atBatBalls']
        self.outs = msg['halfInningOuts']

        self.on_blase = ['', '', '']
        self.bases_occupied = msg['baserunnerCount']
        if msg['baserunnerCount'] > 0:
            for pid, base in zip(msg['baseRunners'], msg['basesOccupied']):
                player_name = player_names.get(pid)
                self.on_blase[base] = player_name or 'runner'
        print(self.away_team, self.home_team, self.away_score, self.home_score, self.inning, self.top_of_inning, self.at_bat, self.pitching, self.strikes, self.balls, self.outs, self.on_blase)
        return pbp


class Announcer(object):

    def __init__(self, calling_for='Fridays'):
        self.calling_for = calling_for
        self.calling_game = BlaseballGlame()
        self.voice = pyttsx3.init()
        self.last_play_by_play = ''

    def on_message(self):
        def callback(ws, message):
            message = ujson.loads(message[2:])
            if message[0] != 'gameDataUpdate':
                return
            for game in message[1]['schedule']:
                if self.calling_for in (game['awayTeamNickname'], game['homeTeamNickname']):
                    pbp = self.calling_game.update(game)
                    if pbp != self.last_play_by_play:
                        self.voice.say(pbp)
                        self.last_play_by_play = pbp
                    break
            quips = []
            quips.extend(self.quip_batting(pbp))
            quips.extend(self.quip_inning())
            quips.extend(self.quip_game_over(pbp))
            quips.extend(self.quip_strike(pbp))
            if random.random() < .3:
                base_quip = self.quip_on_base()
                quips.extend(base_quip)

            for quip in quips:
                self.voice.say(quip)

            self.voice.runAndWait()
        return callback

    def quip_game_over(self, play_by_play):
        if "Game over" not in play_by_play:
            return []
        return ['{} {}, {} {}'.format(
                self.calling_game.away_team,
                self.calling_game.away_score,
                self.calling_game.home_team,
                self.calling_game.home_score,
        )]

    def quip_outs(self):
        if self.calling_game.outs > 0:
            return random.choice([
                '{} outs left'.format(self.calling_game.outs),
                '{} with {} outs'.format(self.calling_game.at_bat, self.calling_game.outs),
                '{} out{} remaining for the {}'.format(
                    3 - self.calling_game.outs,
                    's' if 3 - self.calling_game.outs > 1 else '',
                    self.calling_game.team_at_bat,
                ),
                '{} have {} out{} left'.format(
                    self.calling_game.team_at_bat,
                    self.calling_game.outs,
                    's' if self.calling_game.outs > 1 else '',
                ),
            ])
        return None

    def quip_strike(self, play_by_play):
        if 'Strike' not in play_by_play:
            return []
        quips = []
        if random.random() < .3:
            out_quip = self.quip_outs()
            if out_quip:
                quips.append(out_quip)
        return quips

    def quip_batting(self, play_by_play):
        """announce number outs, runners on base, pitcher"""
        if 'batting' not in play_by_play:
            return []
        quips = []
        out_quip = self.quip_outs()
        if out_quip:
            quips.append(out_quip)
        if random.random() < .3:
            quips.append('{} pitching.'.format(self.calling_game.pitching))
        quips.extend(self.quip_on_base())
        return quips

    def quip_inning(self):
        """announce current inning, score"""
        if not self.calling_game.batting_change:
            return []
        quips = []
        quips.append('{} of the {}'.format(
            'top' if self.calling_game.top_of_inning else 'bottom',
            pronounce_inning(self.calling_game.inning),
        ))
        if random.random() < .5:
            quips.append('{} {}, {} {}'.format(
                self.calling_game.away_team,
                self.calling_game.away_score,
                self.calling_game.home_team,
                self.calling_game.home_score,
            ))
        return quips

    def quip_on_base(self):
        if self.calling_game.has_runners:
            runners = self.calling_game.runners[-1]
            return [random.choice([
                '{} runner{} on base'.format(
                    self.calling_game.bases_occupied,
                    's' if self.calling_game.bases_occupied > 1 else '',
                ),
                '{} on {}'.format(runners[0], runners[1]),
            ])]
        return []


def main():
    announcer = Announcer(calling_for='Millennials')
    while 1:
        websocket.enableTrace(True)
        ws = websocket.WebSocketApp(
            'wss://blaseball.com/socket.io/?EIO=3&transport=websocket',
            on_message=announcer.on_message(),
        )
        exit = ws.run_forever()
        if exit is False:
            return
        time.sleep(0)


def test():
    announcer = Announcer(calling_for='Millennials')

    test_dump = [
        'gameDataUpdate',
        {
            'schedule': [
                {
                    u'_id': u'4d26c148-3fe8-4b9a-9f64-7c10a0607423',
                    u'atBatBalls': 0,
                    u'atBatStrikes': 0,
                    u'awayBatter': u'',
                    u'awayBatterName': u'',
                    u'awayOdds': 0.5585154403765049,
                    u'awayPitcher': u'bf122660-df52-4fc4-9e70-ee185423ff93',
                    u'awayPitcherName': u'Walton Sports',
                    u'awayScore': 2,
                    u'awayStrikes': 3,
                    u'awayTeam': u'a37f9158-7f82-46bc-908c-c9e2dda7c33b',
                    u'awayTeamBatterCount': 11,
                    u'awayTeamColor': u'#6388ad',
                    u'awayTeamEmoji': u'0x1F450',
                    u'awayTeamName': u'New York Millennials',
                    u'awayTeamNickname': u'Millennials',
                    u'baseRunners': [u'd8ee256f-e3d0-46cb-8c77-b1f88d8c9df9'],
                    u'baserunnerCount': 1,
                    u'basesOccupied': [0],
                    u'day': 93,
                    u'finalized': False,
                    u'gameComplete': False,
                    u'gameStart': True,
                    u'halfInningOuts': 2,
                    u'halfInningScore': 0,
                    u'homeBatter': u'',
                    u'homeBatterName': u'',
                    u'homeOdds': 0.44148455962349503,
                    u'homePitcher': u'd0d7b8fe-bad8-481f-978e-cb659304ed49',
                    u'homePitcherName': u'Adalberto Tosser',
                    u'homeScore': 0,
                    u'homeStrikes': 3,
                    u'homeTeam': u'8d87c468-699a-47a8-b40d-cfb73a5660ad',
                    u'homeTeamBatterCount': 5,
                    u'homeTeamColor': u'#593037',
                    u'homeTeamEmoji': u'0x1F980',
                    u'homeTeamName': u'Baltimore Crabs',
                    u'homeTeamNickname': u'Crabs',
                    u'inning': 2,
                    u'isPostseason': False,
                    u'lastUpdate': u"Comfort Septemberish reaches on fielder's choice. Tamara Crankit out at second base.",
                    u'outcomes': [],
                    u'phase': 3,
                    u'rules': u'4ae9d46a-5408-460a-84fb-cbd8d03fff6c',
                    u'season': 2,
                    u'seriesIndex': 1,
                    u'seriesLength': 3,
                    u'shame': False,
                    u'statsheet': u'ec7b5639-ddff-4ffa-8181-87710bbd02cd',
                    u'terminology': u'b67e9bbb-1495-4e1b-b517-f1444b0a6c8b',
                    u'topOfInning': True,
                u'weather': 11}
            ]
        },
    ]

    announcer.on_message()(None, '42' + ujson.dumps(test_dump))
    return




if __name__ == '__main__':
    main()
