import pygame
import sys
from math import sin
import random
import json
import os
import asyncio
import time
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from collections import deque
 
 
# Initialize Pygame
pygame.init()

map = []


# read map as a 2d list from a text file
script_dir = os.path.dirname(os.path.abspath(__file__))
map_path = os.path.join(script_dir, "map.txt")
with open(map_path, "r") as f:
    map = f.read().splitlines()
    map = [list(row) for row in map]

color_dict = {
    "G": (0, 255, 0, 120),  # Grass
    "W": (0, 0, 255, 120),  # Water
    "M": (128, 128, 128, 120),  # Mountain
    "F": (34, 139, 34, 120),  # Forest
    "D": (139, 69, 19, 120),  # Desert
    "S": (255, 255, 0, 120),  # Sand
    "R": (255, 0, 0, 120),  # Road
    "B": (0, 0, 0, 120),  # Building
    "T": (255, 165, 0, 120),  # Tree
}

tile_stamina_cost = {
    "G": 1,  # Grass
    "W": 5,  # Water
    "M": 3,  # Mountain
    "F": 2,  # Forest
    "D": 1,  # Desert
    "S": 1,  # Sand
    "R": 1,  # Road
    "B": 0,  # Building (impassable)
    "T": 2,  # Tree
}

def create_map_surface():
    """Create and cache the map as a single surface with transparency."""
    map_height = len(map)
    map_width = len(map[0])
    tile_size = 20
    
    # Create a surface with alpha for the entire map
    map_surface = pygame.Surface((map_width * tile_size, map_height * tile_size), pygame.SRCALPHA)
    map_surface.fill((0, 0, 0, 0))  # Transparent background
    
    for y, row in enumerate(map):
        for x, tile in enumerate(row):
            color = color_dict.get(tile, (255, 255, 255, 120))
            pygame.draw.rect(map_surface, color, (x * tile_size, y * tile_size, tile_size, tile_size))
    
    return map_surface

def draw_map(surface, map_surface, cam_x, cam_y, cam_zoom):
    """Draw the cached map surface with camera transform."""
    tile_size = 20
    scaled_width = int(map_surface.get_width() * cam_zoom)
    scaled_height = int(map_surface.get_height() * cam_zoom)
    
    # Scale the map surface
    scaled_map = pygame.transform.scale(map_surface, (scaled_width, scaled_height))
    
    # Draw at camera position
    surface.blit(scaled_map, (-cam_x, -cam_y))

def draw_bar(surface, x, y, width, height, current_value, max_value, bg_color, fg_color):
    """Draw a status bar (HP, stamina, etc.)
    
    Args:
        surface: pygame surface to draw on
        x, y: top-left position of bar
        width, height: dimensions of bar
        current_value: current amount (e.g., current HP)
        max_value: maximum amount (e.g., max HP)
        bg_color: tuple (R, G, B) for background color
        fg_color: tuple (R, G, B) for foreground/filled color
    """
    # Background
    pygame.draw.rect(surface, bg_color, (x, y, width, height))
    
    # Foreground (filled proportional to current/max ratio)
    ratio = max(0, min(1, current_value / max_value)) if max_value > 0 else 0
    filled_width = width * ratio
    pygame.draw.rect(surface, fg_color, (x, y, filled_width, height))


# ============= AGENT SYSTEM =============

class TroopBehaviour(CyclicBehaviour):
    """Base behaviour class for troop decision-making. Subclass to create different strategies."""
    
    def __init__(self, mode="normal"):
        super().__init__()
        self.mode = mode
    
    async def on_start(self):
        """Called when behaviour starts."""
        pass
    
    async def on_end(self):
        """Called when behaviour ends."""
        pass
    
    async def run(self):
        """Entry point for SPADE CyclicBehaviour."""
        await self.action()
    
    async def action(self):
        """Main decision-making logic. Override in subclasses."""
        troop = self.agent.troop
        # Process incoming SPADE-style messages in agent inbox (if any)
        if hasattr(self.agent, 'inbox') and self.agent.inbox:
            while self.agent.inbox:
                msg = self.agent.inbox.pop(0)
                try:
                    payload = json.loads(msg.body)
                except Exception:
                    payload = {}
                # expected payload: { 'type': 'order', 'leader': {'name':..., 'squad':..., 'x':..., 'y':...}, 'command': 'delete'|'go_to', 'args': {...} }
                if payload.get('type') == 'order':
                    leader_info = payload.get('leader')
                    command = payload.get('command')
                    args = payload.get('args')
                    acknowledged = troop.respond_to_order(leader_info, command, args)
                    # send ack back to leader if requested
                    if acknowledged and leader_info:
                        leader_name = leader_info.get('name') if isinstance(leader_info, dict) else getattr(leader_info, 'name', None)
                        if leader_name:
                            leader_troop = name_to_troop.get(leader_name)
                            if leader_troop:
                                ack_msg = Message()
                                ack_msg.body = json.dumps({'type':'ack','from':troop.name,'command':command})
                                # send via decider map if available
                                if hasattr(self.agent, 'send_spade_message') and leader_troop in decider_map:
                                    self.agent.send_spade_message(leader_troop, ack_msg)
        
        # Detect enemies
        troop.detect_enemies(self.agent.all_troops)
        
        # React to detected enemies
        if troop.detected_enemies:
            await self.decide_combat(troop)
        # Rest if stamina is low
        elif troop.stamina <= 20:
            troop.rest()
        # Follow path if one exists
        elif troop.planned_actions:
            troop.follow_path()
        # Plan new path if idle
        else:
            await self.decide_idle(troop)
        
        await asyncio.sleep(0.1)
    
    async def decide_combat(self, troop):
        """Decide combat action. Override for different strategies."""
        troop.react(troop.detected_enemies[0])
    
    async def decide_idle(self, troop):
        """Decide what to do when idle. Override for different strategies."""
        if random.random() < 0.1:  # 10% chance to plan new path
            target_x = random.randint(0, len(map[0]) - 1)
            target_y = random.randint(0, len(map) - 1)
            troop.plan_path(target_x, target_y)
        else:
            troop.rest()


class TroopAgent(Agent):
    """Base SPADE agent for individual troop units."""
    
    def __init__(self, jid, password, troop_instance, all_troops, mode="normal"):
        super().__init__(jid, password)
        self.troop = troop_instance
        self.all_troops = all_troops
        self.mode = mode
        self.decision_behaviour = None
    
    async def setup(self):
        """Initialize agent and add behaviour."""
        self.decision_behaviour = TroopBehaviour(mode=self.mode)
        self.add_behaviour(self.decision_behaviour)
        print(f"[AGENT] {self.name} started in mode {self.mode}")
    
    def set_mode(self, new_mode):
        """Change the decision mode at runtime."""
        self.mode = new_mode
        if self.decision_behaviour:
            self.decision_behaviour.mode = new_mode
        print(f"[AGENT] {self.name} mode changed to {new_mode}")


class weapon:
    def __init__(self, name, damage, range, accuracy, durability, ammo_type, degrade_rate=0):
        self.name = name
        self.damage = damage
        self.range = range
        self.accuracy = accuracy
        self.durability = durability
        self.ammo_type = ammo_type
        self.degrade_rate = degrade_rate
    def attack(self, user, target):
        # Calculate hit chance based on accuracy
        if self.durability <= 0:
            print(f"{self.name} is broken and cannot be used!")
            return
        if (self.ammo_type not in user.ammo or user.ammo[self.ammo_type] <= 0) and self.ammo_type != "none":
            print(f"{self.name} is out of ammo!")
            return
        hit_chance = self.accuracy / 100
        if random.random() <= hit_chance:
            target.health -= self.damage
            print(f"{user} used {self.name}! {target} took {self.damage} damage.")
            self.durability -= self.degrade_rate
        else:
            print(f"{user} missed with {self.name}!")

class troop:
    def __init__(self, x, y, name="Unnamed", squad="", team="neutral", color=(255, 0, 0), health=100, armor=0, stamina=100, speed=5, view_range=50, weapons=None, ammo=None, planned_actions=None, detected_enemies=None):
        self.x = x
        self.y = y
        self.name = name
        self.squad = squad
        self.team = team
        self.color = color
        self.health = health
        self.armor = armor
        self.stamina = stamina
        self.speed = speed
        self.view_range = view_range
        self.weapons = weapons if weapons is not None else []
        self.planned_actions = planned_actions if planned_actions is not None else []
        self.active_slot = 0
        self.ammo = ammo if ammo is not None else {}
        self.detected_enemies = detected_enemies if detected_enemies is not None else []
        self.rest_rate = -3  # Stamina points regenerated per rest action
        self.panic_timer = 0  # Timer to track how long the troop has been in panic mode, will use hp as stamina if enemies are detected
    
    def __str__(self):
        return f"Troop {self.name} at ({self.x}, {self.y}) with {self.health} health, {self.stamina} stamina"
    
    
    def attack(self, target):
        if self.weapons:
            weapon = self.weapons[self.active_slot]
            weapon.attack(self, target)
        else:
            print(f"{self} has no weapons to attack with!")
    
    
    
    def plan_path(self, target_x, target_y, alg=1):
        if alg==0:
            # Path planning: BFS algorithm to append path steps to planned_actions
            
            queue = deque()
            queue.append((self.x, self.y, []))  # (current_x, current_y, path_so_far)
            visited = set()
            visited.add((self.x, self.y))
            while queue:
                current_x, current_y, path_so_far = queue.popleft()
                if (current_x, current_y) == (target_x, target_y):
                    #print(f"[DEBUG] {self}: planned path to ({target_x}, {target_y}) with {len(path_so_far)} steps")
                    #print(f"[DEBUG] {self}: path = {path_so_far}")
                    self.planned_actions.extend(path_so_far)
                    return 
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    new_x, new_y = current_x + dx, current_y + dy
                    if 0 <= new_x < len(map[0]) and 0 <= new_y < len(map) and (new_x, new_y) not in visited:
                        tile_type = map[new_y][new_x]
                        if tile_stamina_cost[tile_type] > 0:  # Check if the tile is passable
                            visited.add((new_x, new_y))
                            queue.append((new_x, new_y, path_so_far + [(new_x, new_y)]))
        if alg==1:
            # Path Planning: UCS algorithm to append path steps to planned_actions
            queue = deque()
            queue.append((self.x, self.y, [], 0))  # (current_x, current_y, path_so_far, cost_so_far)
            visited = set()
            visited.add((self.x, self.y))
            while queue:
                current_x, current_y, path_so_far, cost_so_far = queue.popleft()
                if (current_x, current_y) == (target_x, target_y):
                    #print(f"[DEBUG] {self}: planned path to ({target_x}, {target_y}) with {len(path_so_far)} steps and cost {cost_so_far}")
                    #print(f"[DEBUG] {self}: path = {path_so_far}")
                    self.planned_actions.extend(path_so_far)
                    return 
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    new_x, new_y = current_x + dx, current_y + dy
                    if 0 <= new_x < len(map[0]) and 0 <= new_y < len(map) and (new_x, new_y) not in visited:
                        tile_type = map[new_y][new_x]
                        stamina_cost = tile_stamina_cost[tile_type]
                        if stamina_cost > 0:  # Check if the tile is passable
                            visited.add((new_x, new_y))
                            queue.append((new_x, new_y, path_so_far + [(new_x, new_y)], cost_so_far + stamina_cost))
        
    
    def stamina_deplete(self, stamina_cost, fail_message="Not enough stamina!"):
        self.panic_timer = max(0, self.panic_timer - 1)  # Reduce panic timer when taking actions
        if self.stamina >= stamina_cost:
            self.stamina -= stamina_cost
            self.rest_rate = -3  # Reset rest rate when taking action
            return True
        else:
            if self.panic_timer > 0:
                sh=self.health 
                self.health -= stamina_cost  # Use health as stamina in panic mode
                print(f"{self} is panicking! Health is being used as stamina. [{sh} -> {self.health}]")
                return True        
            else:
                print(fail_message)
                return False

    def follow_path(self):
        if self.planned_actions:
            next_x, next_y = self.planned_actions[0]
            tile_type = map[next_y][next_x]
            stamina_cost = tile_stamina_cost[tile_type]
            #print(f"[DEBUG] {self}: following path step to ({next_x}, {next_y}) from ({self.x}, {self.y}), stamina cost={stamina_cost}, remaining stamina={self.stamina}")
            if self.stamina_deplete(stamina_cost, fail_message=f"{self} cannot move to ({next_x}, {next_y}) due to insufficient stamina!"):
                self.x, self.y = next_x, next_y
                self.stamina -= stamina_cost
                self.planned_actions.pop(0)
                #print(f"[DEBUG] {self}: moved to ({self.x}, {self.y}), remaining planned steps={len(self.planned_actions)}")
        else:
            print(f"{self} has no planned actions to follow!")   
    
    def react(self, detected_enemy):
        # if detected_enemy is within view range, plan a path to attack or retreat based on health
        distance = abs(self.x - detected_enemy.x) + abs(self.y - detected_enemy.y)
        if distance <= self.view_range:
            if len(self.weapons) > 0 and distance <= self.weapons[self.active_slot].range and self.health > 50:
                # Attack the enemy
                self.attack(detected_enemy)
            elif len(self.weapons) > 0 and self.health > 50:
                # Plan path to attack
                self.plan_path(detected_enemy.x, detected_enemy.y)
            else:
                self.panic_timer = len(self.detected_enemies) * 3
                # Plan path to retreat (move away from enemy)
                retreat_x = self.x + (self.x - detected_enemy.x)
                retreat_y = self.y + (self.y - detected_enemy.y)
                # Ensure retreat coordinates are within map bounds
                retreat_x = max(0, min(retreat_x, len(map[0]) - 1))
                retreat_y = max(0, min(retreat_y, len(map) - 1))
                self.plan_path(retreat_x, retreat_y)
    
    def detect_enemies(self, troops):
        self.detected_enemies = []
        for troop in troops:
            if troop != self and troop.team != self.team:
                distance = abs(self.x - troop.x) + abs(self.y - troop.y)
                if distance <= self.view_range:
                    self.detected_enemies.append(troop)
        #print(f"{self} detected {len(self.detected_enemies)} enemies within view range.")
    
    def respond_to_order(self, leader, command, args=None):
        """Default response to a squad leader's order. Returns True if acknowledged."""
        # leader may be an object or a dict with 'squad' and 'name'
        leader_squad = None
        leader_name = None
        if isinstance(leader, dict):
            leader_squad = leader.get('squad')
            leader_name = leader.get('name')
        else:
            leader_squad = getattr(leader, 'squad', None)
            leader_name = getattr(leader, 'name', None)
        # Only respond if the leader's squad matches this troop's squad string
        if leader_squad and (leader_squad in self.squad):
            # Different response based on command type
            if command == "discover":
                print(f"{self.name}: Yessir! (discovered by {leader_name})")
            else:
                print(f"{self.name}: Roger! (executing {command} from {leader_name})")
            # Execute the command locally if appropriate
            if command == "delete":
                self.planned_actions.clear()
            elif command == "go_to" and args is not None:
                # args can be a tuple (x, y) or dict with 'x','y'
                if isinstance(args, tuple) and len(args) >= 2:
                    tx, ty = args[0], args[1]
                elif isinstance(args, dict):
                    tx, ty = args.get("x"), args.get("y")
                else:
                    return True
                if tx is not None and ty is not None:
                    self.plan_path(int(tx), int(ty))
            return True
        return False
    
    def rest(self): 
        # Regenerate stamina at a progressive rate, up to 5 per turn   
        
        self.rest_rate = min(self.rest_rate+1, 5) 
        if self.rest_rate>0:
            self.stamina = min(100, self.stamina + self.rest_rate) 
            if self.stamina == 100 and self.rest_rate == 5:
                self.hp = min(100, self.health + 1)  # Regenerate health slowly when fully rested
    
    def draw(self, surface, cam_x, cam_y, cam_zoom):
        tile_size = 20 * cam_zoom
        color = self.color
        # Ensure color has 4 components for RGBA
        if len(color) == 3:
            color = color + (255,)
        
        # Draw troop square
        pygame.draw.rect(surface, color, (self.x * tile_size - cam_x, self.y * tile_size - cam_y, tile_size, tile_size))
        pygame.draw.rect(surface, (0, 0, 0), (self.x * tile_size - cam_x, self.y * tile_size - cam_y, tile_size, tile_size), 1)  # Black border for visibility
        
        # Bar dimensions
        bar_width = tile_size * 0.8
        bar_height = max(2, int(tile_size * 0.15))
        bar_x = self.x * tile_size - cam_x + (tile_size - bar_width) / 2
        
        # Draw HP bar (red/green) above troop
        hp_bar_y = self.y * tile_size - cam_y - bar_height * 2 - 4
        draw_bar(surface, bar_x, hp_bar_y, bar_width, bar_height, self.health, 100, (255, 0, 0), (0, 255, 0))
        
        # Draw stamina bar (orange/yellow) below HP bar
        stamina_bar_y = self.y * tile_size - cam_y - bar_height - 2
        draw_bar(surface, bar_x, stamina_bar_y, bar_width, bar_height, self.stamina, 100, (139, 69, 19), (255, 165, 0))
      
class SquadLeader(troop):
    """Squad leader with ability to broadcast orders to nearby squad members."""
    def __init__(self, x, y, name="Leader", squad="", team="neutral", range=None, **kwargs):
        # If caller supplied a 'range' value, map it to the existing 'view_range' field
        if range is not None:
            kwargs.setdefault('view_range', range)
        super().__init__(x, y, name=name, squad=squad, team=team, **kwargs)
        # Track pending responses: {order_id: {'troops': set of troop names, 'timestamp': time, 'command': cmd}}
        self.pending_responses = {}
        self.order_counter = 0

    def broadcast_and_command(self, command, args, all_troops):
        """Broadcasts presence and then issues a command to squad members in range.
        Sequence: announce discovery (Yessir!) -> issue command (Roger!).
        """
        print(f"{self.name} broadcasting to squad='{self.squad}' at ({self.x},{self.y}) using leader's view_range={self.view_range}")
        responders = []
        order_id = self.order_counter
        self.order_counter += 1
        
        for t in all_troops:
            if t is not self:
                distance = abs(self.x - t.x) + abs(self.y - t.y)
                # Use the squad leader's view_range to decide recipients
                if distance <= getattr(self, 'view_range', 0) and (self.squad in t.squad):
                    # First: send discovery message (troops respond "Yessir!")
                    discovery_msg = Message()
                    payload = {
                        'type': 'discovery',
                        'leader': {'name': self.name, 'squad': self.squad, 'x': self.x, 'y': self.y},
                        'command': 'discover',
                    }
                    discovery_msg.body = json.dumps(payload)
                    if t in decider_map:
                        decider_map[t].inbox.append(discovery_msg)
                    
                    # Second: send command message (troops respond "Roger!")
                    msg = Message()
                    payload = {
                        'type': 'order',
                        'leader': {'name': self.name, 'squad': self.squad, 'x': self.x, 'y': self.y},
                        'command': command,
                        'args': args,
                    }
                    msg.body = json.dumps(payload)
                    # send via decider inbox if available
                    if t in decider_map:
                        decider_map[t].inbox.append(msg)
                        responders.append(t.name)
                        # Track pending Roger response from this troop
                        if t in decider_map:
                            decider_map[t].pending_orders[self.name] = {'timestamp': time.time(), 'command': command}
                    else:
                        # fallback: direct call
                        ack = t.respond_to_order(self, command, args)
                        if ack:
                            responders.append(t)
        
        # Track pending responses
        self.pending_responses[order_id] = {
            'troops': set(responders),
            'timestamp': time.time(),
            'command': command
        }
        print(f"{self.name} issued '{command}' to {len(responders)} troops")
    
    def check_roger_timeout(self, timeout_seconds=10):
        """Check for troops that haven't sent Roger! within timeout."""
        current_time = time.time()
        timed_out = []
        for order_id, resp_info in list(self.pending_responses.items()):
            elapsed = current_time - resp_info['timestamp']
            if elapsed > timeout_seconds:
                timed_out.append((order_id, resp_info['troops'], resp_info['command'], elapsed))
        for order_id, troop_names, command, elapsed in timed_out:
            for troop_name in troop_names:
                print(f"[TIMEOUT] {self.name}: No Roger! from {troop_name} for {command} after {elapsed:.1f}s")
            del self.pending_responses[order_id]

# Screen settings
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Simulator")

# Clock for controlling frame rate
clock = pygame.time.Clock()
 
running = True

game_time = 0
game_cam_zoom = 1.0
game_cam_x = 0
game_cam_y = 0 

red_leader = SquadLeader(28, 28, name="RedLeader", squad="R", team="red", color=(155, 0, 0),range=30)
blue_leader = SquadLeader(118, 118, name="BlueLeader", squad="B", team="blue", color=(0, 0, 155),range=30)


red_troops = [
    troop(5, 5, name="John Doe", squad="R", team="red", color=(255, 0, 0), weapons=[weapon("Rifle", 10, 5, 15, 100, "bullets")], ammo={"bullets": 30}),
    troop(0, 10, name="Jane Smith", squad="R0", team="red", color=(200, 0, 0), weapons=[weapon("Pistol", 5, 3, 6, 100, "bullets")], ammo={"bullets": 15}), 
    troop(5, 15, name="Reddington Stone", squad="R00", team="red", color=(255, 55, 0), weapons=[weapon("Bow", 8, 4, 10, 100, "arrows")], ammo={"arrows": 20}),
    troop(0, 20, name="Sam Johns", squad="R01", team="red", color=(180, 30, 0), weapons=[weapon("Shotgun", 15, 2, 7, 100, "shells")], ammo={"shells": 10}), 
    troop(5, 25, name="Major Major", squad="R1", team="red", color=(200, 70, 255), weapons=[weapon("Sniper", 20, 10, 40, 100, "bullets")], ammo={"bullets": 5}),
    troop(0, 30, name="Rob", squad="R10", team="red", color=(200, 10, 15), weapons=[weapon("SMG", 7, 4, 8, 100, "bullets")], ammo={"bullets": 50})
]

blue_troops = [
    troop(115, 115, name="Alice Blue", squad="B", team="blue", color=(0, 0, 255), weapons=[weapon("Rifle", 10, 5, 15, 100, "bullets")], ammo={"bullets": 30}),
    troop(120, 110, name="Bob Cyan", squad="B0", team="blue", color=(0, 100, 255), weapons=[weapon("Pistol", 5, 3, 6, 100, "bullets")], ammo={"bullets": 15}),
    troop(110, 120, name="Cyanne", squad="B00", team="blue", color=(0, 100, 205), weapons=[weapon("Bow", 8, 4, 10, 100, "arrows")], ammo={"arrows": 20}),
    troop(125, 115, name="Dave Azure", squad="B01", team="blue", color=(0, 50, 255), weapons=[weapon("Shotgun", 15, 2, 7, 100, "shells")], ammo={"shells": 10}),
    troop(115, 125, name="Eve Navy", squad="B1", team="blue", color=(0, 0, 200), weapons=[weapon("Sniper", 20, 10, 40, 100, "bullets")], ammo={"bullets": 5}),
    troop(120, 120, name="Frank", squad="B10", team="blue", color=(0, 0, 180), weapons=[weapon("SMG", 7, 4, 8, 100, "bullets")], ammo={"bullets": 50})
]

troops= red_troops + blue_troops


troops.append(red_leader)
troops.append(blue_leader)

agents = []
agent_tasks = []

# Pre-render the map surface
cached_map_surface = create_map_surface()

# Instead of using actual SPADE agents with XMPP, we'll use lightweight decision objects
class SimpleTroopDecider:
    """Lightweight alternative to SPADE agents for single-process simulation."""
    def __init__(self, troop_instance, all_troops, mode="normal"):
        self.troop = troop_instance
        self.all_troops = all_troops
        self.mode = mode
        self.behaviour_instance = TroopBehaviour(mode=mode)
        # Manually set the agent reference (normally done by SPADE)
        self.behaviour_instance.agent = self
        # simple in-process inbox to simulate SPADE messages
        self.inbox = []
        # Track pending orders with timestamps for timeout detection
        self.pending_orders = {}  # {leader_name: {'timestamp': time, 'command': cmd}}

    def send_spade_message(self, target_troop, message):
        """Simulate sending a SPADE Message to another troop's decider inbox."""
        if target_troop in decider_map:
            decider_map[target_troop].inbox.append(message)
    
    def check_order_timeout(self, timeout_seconds=10):
        """Check for orders that timed out waiting for confirmation."""
        current_time = time.time()
        timed_out = []
        for leader_name, order_info in self.pending_orders.items():
            elapsed = current_time - order_info['timestamp']
            if elapsed > timeout_seconds:
                timed_out.append((leader_name, order_info['command'], elapsed))
        for leader_name, command, elapsed in timed_out:
            print(f"[TIMEOUT] {self.troop.name}: No confirmation for {command} from {leader_name} after {elapsed:.1f}s")
            del self.pending_orders[leader_name]
    
    async def decide(self):
        """Execute decision logic."""
        self.check_order_timeout()
        await self.behaviour_instance.action()
    
    def set_mode(self, new_mode):
        """Change the decision mode."""
        self.mode = new_mode
        self.behaviour_instance.mode = new_mode
        print(f"[DECIDER] {self.troop.name} mode changed to {new_mode}")


# Create deciders for each troop
deciders = []
decider_map = {}
name_to_troop = {}

# Assign modes to troops by index (defaults to 'normal')
mode_assignments = {
    0: "normal",
    1: "normal",
    2: "normal",
    3: "normal",
    4: "normal",
    5: "normal",
    6: "normal",
    7: "normal",
    8: "normal",
    9: "normal",
    10: "normal",
    11: "normal",
    12: "normal",
}
for idx, t in enumerate(troops):
    mode = mode_assignments.get(idx, "normal")
    decider = SimpleTroopDecider(t, troops, mode)
    deciders.append(decider)
    decider_map[t] = decider
    name_to_troop[t.name] = t

while running:
    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_EQUALS:  # Zoom in
                # Get center of screen in world coordinates
                center_world_x = (WIDTH / 2 + game_cam_x) / (20 * game_cam_zoom)
                center_world_y = (HEIGHT / 2 + game_cam_y) / (20 * game_cam_zoom)
                # Apply zoom
                game_cam_zoom *= 1.1
                # Adjust camera to keep center point at center of screen
                game_cam_x = center_world_x * (20 * game_cam_zoom) - WIDTH / 2
                game_cam_y = center_world_y * (20 * game_cam_zoom) - HEIGHT / 2
            if event.key == pygame.K_MINUS:  # Zoom out
                # Get center of screen in world coordinates
                center_world_x = (WIDTH / 2 + game_cam_x) / (20 * game_cam_zoom)
                center_world_y = (HEIGHT / 2 + game_cam_y) / (20 * game_cam_zoom)
                # Apply zoom
                game_cam_zoom /= 1.1
                # Adjust camera to keep center point at center of screen
                game_cam_x = center_world_x * (20 * game_cam_zoom) - WIDTH / 2
                game_cam_y = center_world_y * (20 * game_cam_zoom) - HEIGHT / 2
    
    # Handle continuous key presses for panning
    keys = pygame.key.get_pressed()
    pan_speed = 10
    if keys[pygame.K_UP]:
        game_cam_y -= pan_speed
    if keys[pygame.K_DOWN]:
        game_cam_y += pan_speed
    if keys[pygame.K_LEFT]:
        game_cam_x -= pan_speed
    if keys[pygame.K_RIGHT]:
        game_cam_x += pan_speed
    
    
    # Update troops with agent-based decisions
    if game_time % 15 == 0:  # Update 4 hz
        # Check for timeouts on both leaders and troops
        for decider in deciders:
            decider.check_order_timeout()
        for t in troops:
            if isinstance(t, SquadLeader):
                t.check_roger_timeout()
        
        # Run all agent decisions concurrently
        async def update_all_agents():
            tasks = [decider.decide() for decider in deciders]
            await asyncio.gather(*tasks)
        
        # Run the async update in a sync context
        try:
            asyncio.run(update_all_agents())
        except RuntimeError as e:
            # If event loop already running, use a different approach
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(update_all_agents())
            loop.close()
        
    
    # Draw
    game_time += 1
    screen.fill([0, 127+int(127*sin(game_time/3600)), 40+int(-40*sin(game_time/3600-180))])  # Fill the screen with background color
    
    # Draw the cached map
    draw_map(screen, cached_map_surface, game_cam_x, game_cam_y, game_cam_zoom)
    
    # Draw troops
    for troop in troops:
        troop.draw(screen, game_cam_x, game_cam_y, game_cam_zoom)
    
    pygame.display.flip()
    clock.tick(60)
 
pygame.quit()
sys.exit()
 
