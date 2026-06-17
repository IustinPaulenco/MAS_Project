import pygame
import sys
from math import sin
import random
import json
import os
import asyncio
import time
import spade
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
    """Draw the cached map surface with camera transform, culling out-of-range tiles."""
    tile_size = 20
    
    # Determine the visible area in unscaled coordinates
    unscaled_cam_x = cam_x / cam_zoom
    unscaled_cam_y = cam_y / cam_zoom
    unscaled_screen_w = surface.get_width() / cam_zoom
    unscaled_screen_h = surface.get_height() / cam_zoom
    
    # Calculate tile ranges (culling invisible tiles)
    start_tile_x = int(unscaled_cam_x // tile_size)
    start_tile_y = int(unscaled_cam_y // tile_size)
    end_tile_x = int((unscaled_cam_x + unscaled_screen_w) // tile_size) + 1
    end_tile_y = int((unscaled_cam_y + unscaled_screen_h) // tile_size) + 1
    
    # Clamp to map boundaries
    start_tile_x = max(0, start_tile_x)
    start_tile_y = max(0, start_tile_y)
    end_tile_x = min(len(map[0]), end_tile_x)
    end_tile_y = min(len(map), end_tile_y)
    
    if start_tile_x >= end_tile_x or start_tile_y >= end_tile_y:
        return
        
    # Crop the map surface to only the visible tiles
    crop_x = start_tile_x * tile_size
    crop_y = start_tile_y * tile_size
    crop_w = (end_tile_x - start_tile_x) * tile_size
    crop_h = (end_tile_y - start_tile_y) * tile_size
    
    visible_rect = pygame.Rect(crop_x, crop_y, crop_w, crop_h)
    visible_map_part = map_surface.subsurface(visible_rect)
    
    # Scale only the visible part
    scaled_width = int(crop_w * cam_zoom)
    scaled_height = int(crop_h * cam_zoom)
    
    if scaled_width <= 0 or scaled_height <= 0:
        return
        
    scaled_map = pygame.transform.scale(visible_map_part, (scaled_width, scaled_height))
    
    # Draw at the correct screen position
    screen_x = (crop_x * cam_zoom) - cam_x
    screen_y = (crop_y * cam_zoom) - cam_y
    
    surface.blit(scaled_map, (screen_x, screen_y))

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
    
    async def run(self):
        """Entry point for SPADE CyclicBehaviour."""
        await self.action()
    
    async def action(self):
        """Main decision-making logic."""
        global game_time
        troop = self.agent.troop
        
        # Dead troop logic: stay connected to prevent crashes, but refuse orders.
        if troop.health <= 0:
            troop.color = (100, 100, 100)  # Turn gray to indicate death
            msg = await self.receive(timeout=0.1)
            if msg:
                try:
                    payload = json.loads(msg.body)
                    if payload.get('type') in ('order', 'discovery'):
                        leader_info = payload.get('leader')
                        if leader_info and 'name' in leader_info:
                            leader_name = leader_info['name']
                            refusal_msg = Message(to=f"{leader_name.replace(' ', '').lower()}@localhost")
                            refusal_msg.body = json.dumps({
                                'type': 'refusal',
                                'from': troop.name,
                                'command': payload.get('command'),
                                'reason': 'KIA'
                            })
                            await self.send(refusal_msg)
                except Exception:
                    pass
            await asyncio.sleep(0.1)
            return
            
        # Process incoming SPADE messages — one blocking receive, then drain extras
        # Using a small positive timeout for the first receive is critical: timeout=0
        # can cause the coroutine to never yield in some SPADE/pyjabber versions,
        # permanently stalling the agent behaviour.
        MAX_DRAIN = 20
        msg = await self.receive(timeout=0.05)
        msgs_to_process = []
        if msg:
            msgs_to_process.append(msg)
            # Drain any additional queued messages (non-blocking)
            for _ in range(MAX_DRAIN):
                extra = await self.receive(timeout=0)
                if not extra:
                    break
                msgs_to_process.append(extra)

        for msg in msgs_to_process:
            try:
                payload = json.loads(msg.body)
                msg_type = payload.get('type')
                if msg_type == 'order':
                    leader_info = payload.get('leader')
                    command = payload.get('command')
                    args = payload.get('args')
                    acknowledged = troop.respond_to_order(leader_info, command, args)
                    if acknowledged and leader_info:
                        leader_name = leader_info.get('name')
                        if leader_name:
                            ack_msg = Message(to=f"{leader_name.replace(' ', '').lower()}@localhost")
                            ack_msg.body = json.dumps({'type':'ack','from':troop.name,'command':command})
                            await self.send(ack_msg)
                elif msg_type == 'discovery':
                    print(f"{troop.name}: Yessir! (discovered by {payload.get('leader', {}).get('name')})")
                elif msg_type == 'ack':
                    print(f"[SPADE] {troop.name} received ACK from {payload.get('from')} for {payload.get('command')}")
                elif msg_type == 'refusal':
                    print(f"[SPADE] {troop.name} received REFUSAL from {payload.get('from')} for {payload.get('command')}: {payload.get('reason')}")
                elif msg_type == 'ping_leader':
                    # Only SquadLeaders respond to pings
                    if isinstance(troop, SquadLeader) and troop.health > 0:
                        from_x = payload.get('from_x', 0)
                        from_y = payload.get('from_y', 0)
                        from_team = payload.get('from_team')
                        from_name = payload.get('from_name')
                        distance = abs(troop.x - from_x) + abs(troop.y - from_y)
                        # Respond only if same team and within this leader's view range
                        if from_team == troop.team and distance <= troop.view_range:
                            pong_msg = Message(to=f"{from_name.replace(' ', '').lower()}@localhost")
                            pong_msg.body = json.dumps({
                                'type': 'pong_leader',
                                'from': troop.name,
                                'leader_x': troop.x,
                                'leader_y': troop.y,
                            })
                            await self.send(pong_msg)
                elif msg_type == 'pong_leader':
                    # Count leader responses
                    troop.leaders_in_range_count += 1
            except Exception:
                pass
        
        # Send pending leader pings
        if troop._leader_ping_pending:
            troop._leader_ping_pending = False
            troop.leaders_in_range_count = 0  # Reset count for new round
            for t in self.agent.all_troops:
                if isinstance(t, SquadLeader) and t is not troop and t.health > 0:
                    ping_msg = Message(to=f"{t.name.replace(' ', '').lower()}@localhost")
                    ping_msg.body = json.dumps({
                        'type': 'ping_leader',
                        'from_name': troop.name,
                        'from_x': troop.x,
                        'from_y': troop.y,
                        'from_team': troop.team,
                    })
                    await self.send(ping_msg)
        
        # --- Wait commands state overrides ---
        if troop.waiting_for_signal:
            if troop.panic_timer > 1:
                troop.waiting_for_signal = False
                print(f"{troop.name}: Panic overrides wait! Breaking free.")
            else:
                if troop.wait_time > game_time:
                    troop.rest()
                else:
                    leaders_nearby = troop.find_leaders_in_range_count()
                    if leaders_nearby:
                        troop.rest()
                        troop.wait_time = game_time + 100  # Re-check in ~100 ticks (~10s at 0.1s/tick)
                    else:
                        print(f"{troop.name}: No leader in range! Breaking wait.")
                        troop.waiting_for_signal = False
                        troop.wait_time = 0
            await asyncio.sleep(0.1)
            return
            
        if troop.wait_time is not None:
            if game_time < troop.wait_time:
                troop.rest()
                await asyncio.sleep(0.1)
                return
            else:
                troop.wait_time = None  # Time elapsed, resume normal behavior
                
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
            old_stamina = troop.stamina
            troop.follow_path()
            # If stamina didn't decrease, they failed to move (did nothing)
            if troop.stamina == old_stamina:
                troop.rest()
        # Plan new path if idle
        else:
            await self.decide_idle(troop)
        
        await asyncio.sleep(0.1)
    
    async def decide_combat(self, troop):
        troop.react(troop.detected_enemies[0])
    
    async def decide_idle(self, troop):
        if random.random() < 0.1:
            target_x = random.randint(0, len(map[0]) - 1)
            target_y = random.randint(0, len(map) - 1)
            troop.plan_path(target_x, target_y)
            
        # Always rest when in the idle state
        troop.rest()

class SquadLeaderBehaviour(TroopBehaviour):
    async def action(self):
        troop = self.agent.troop
        
        if troop.health > 0:
            # Broadcast pending manual commands
            while self.agent.commands_to_broadcast:
                cmd, args = self.agent.commands_to_broadcast.pop(0)
                await self.broadcast_and_command(cmd, args, self.agent.all_troops)
                
                if cmd == "wait_for_signal":
                    # Leader also waits — directly set own state (no SPADE round-trip)
                    delay = args.get("delay", 5) if isinstance(args, dict) else 5
                    delay_ticks = int(delay / 0.1)  # convert seconds to ~ticks (0.1s each)
                    troop.wait_time = game_time + delay_ticks
                    print(f"[{troop.name}] Also waiting with squad for {delay}s ({delay_ticks} ticks).")
                    
                    async def send_now_later(delay_seconds, leader=troop):
                        await asyncio.sleep(delay_seconds)
                        if leader.health > 0:
                            print(f"[{leader.name}] Wait timer expired! Releasing self and squad.")
                            # Release the leader directly
                            leader.waiting_for_signal = False
                            leader.wait_time = 0
                            # Release the squad via SPADE
                            self.agent.commands_to_broadcast.append(("now", None))
                            
                    asyncio.create_task(send_now_later(delay))
                
                elif cmd == "now":
                    # Also directly release the leader themselves
                    troop.waiting_for_signal = False
                    troop.wait_time = 0
                
            # Randomly issue commands
            rand_val = random.random()
            if rand_val < 0.01:
                self.agent.commands_to_broadcast.append(("go_to", {"x": troop.x, "y": troop.y}))
                print(f"{troop.name} randomly calls the squad to rally at ({troop.x}, {troop.y})!")
            elif rand_val < 0.02:
                self.agent.commands_to_broadcast.append(("wait_for_signal", {"delay": 5}))
                print(f"{troop.name} randomly orders the squad to wait for 5 seconds!")
            
        # Perform normal troop behaviour (includes processing inbox, moving, etc.)
        await super().action()


    async def broadcast_and_command(self, command, args, all_troops):
        troop = self.agent.troop
        print(f"{troop.name} broadcasting to squad='{troop.squad}' at ({troop.x},{troop.y}) using SPADE")
        responders = []
        
        for t in all_troops:
            if t is not troop:
                distance = abs(troop.x - t.x) + abs(troop.y - t.y)
                if distance <= getattr(troop, 'view_range', 0) and t.squad.startswith(troop.squad):
                    target_jid = f"{t.name.replace(' ', '').lower()}@localhost"
                    
                    discovery_msg = Message(to=target_jid)
                    payload = {
                        'type': 'discovery',
                        'leader': {'name': troop.name, 'squad': troop.squad, 'x': troop.x, 'y': troop.y},
                        'command': 'discover',
                    }
                    discovery_msg.body = json.dumps(payload)
                    await self.send(discovery_msg)
                    
                    msg = Message(to=target_jid)
                    payload = {
                        'type': 'order',
                        'leader': {'name': troop.name, 'squad': troop.squad, 'x': troop.x, 'y': troop.y},
                        'command': command,
                        'args': args,
                    }
                    msg.body = json.dumps(payload)
                    await self.send(msg)
                    responders.append(t.name)
        
        print(f"{troop.name} issued '{command}' to {len(responders)} troops via SPADE")

class SquadLeaderAgent(Agent):
    """Base SPADE agent, acts as a superclass for TroopAgent."""
    def __init__(self, jid, password, troop_instance, all_troops, mode="normal"):
        super().__init__(jid, password)
        self.troop = troop_instance
        self.all_troops = all_troops
        self.mode = mode
        self.commands_to_broadcast = []

    async def setup(self):
        self.decision_behaviour = SquadLeaderBehaviour(mode=self.mode)
        self.add_behaviour(self.decision_behaviour)
        print(f"[AGENT] {self.name} (SquadLeader) started in mode {self.mode}")

class TroopAgent(SquadLeaderAgent):
    """SPADE agent for individual troop units, inheriting from SquadLeaderAgent."""
    async def setup(self):
        self.decision_behaviour = TroopBehaviour(mode=self.mode)
        self.add_behaviour(self.decision_behaviour)
        print(f"[AGENT] {self.name} (Troop) started in mode {self.mode}")


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
        self.waiting_for_signal = False
        self.wait_time = 0
        self.leaders_in_range_count = 0  # Updated by SPADE pong responses
        self._leader_ping_pending = False  # Flag to trigger leader ping broadcast
    
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
    
    def find_leaders_in_range_count(self):
        """Trigger a SPADE ping to all leaders and return last known count.
        
        Sets a flag so the agent behaviour sends ping_leader messages on the
        next tick. Returns the count from the previous ping round (pong_leader
        responses already received). Converges after 1-2 ticks."""
        self._leader_ping_pending = True
        return self.leaders_in_range_count
    
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
        # Only respond if the leader's squad matches the start of this troop's squad string
        if leader_squad and self.squad.startswith(leader_squad):
            # Different response based on command type
            if command == "discover":
                print(f"{self.name}: Yessir! (discovered by {leader_name})")
            else:
                print(f"{self.name}: Roger! (executing {command} from {leader_name})")
            # Execute the command locally if appropriate
            if command == "delete":
                self.planned_actions.clear()
            elif command == "wait_for_signal":
                self.waiting_for_signal = True
            elif command == "now":
                self.waiting_for_signal = False
                self.wait_time = None
            elif command == "wait_until_time" and args is not None:
                if isinstance(args, dict) and "time" in args:
                    self.wait_time = args["time"]
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
        if range is not None:
            kwargs.setdefault('view_range', range)
        super().__init__(x, y, name=name, squad=squad, team=team, **kwargs)
        self.pending_responses = {}
        self.order_counter = 0

    def broadcast_and_command(self, command, args, all_troops):
        """Pass the command to the SPADE agent to broadcast."""
        if hasattr(self, 'agent') and self.agent is not None:
            self.agent.commands_to_broadcast.append((command, args))
            print(f"{self.name} queued command '{command}' to SPADE agent.")
        else:
            print(f"[ERROR] {self.name} has no SPADE agent attached to send commands!")
    
    def check_roger_timeout(self, timeout_seconds=10):
        # Delegate timeouts to SPADE agents, empty for now
        pass

name_to_troop = {}
agents = []
game_time = 0

async def main():
    global agents, name_to_troop, game_time
    # Screen settings
    WIDTH, HEIGHT = 800, 600
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Simulator")
    
    # Clock for controlling frame rate
    clock = pygame.time.Clock()
     
    running = True
    
    game_cam_zoom = 1.0
    game_cam_x = 0
    game_cam_y = 0 
    
    red_leader = SquadLeader(28, 28, name="RedLeader", squad="R", team="red", color=(155, 0, 0),range=30)
    blue_leader = SquadLeader(118, 118, name="BlueLeader", squad="B", team="blue", color=(0, 0, 155),range=30)
    
    red_general0 = SquadLeader(18, 28, name="RedGeneral0", squad="R0", team="red", color=(155, 25, 0),range=30)
    blue_general0 = SquadLeader(128, 118, name="BlueGeneral0", squad="B0", team="blue", color=(0, 25, 155),range=30)
    
    red_general1 = SquadLeader(28, 18, name="RedGeneral1", squad="R1", team="red", color=(155, 0, 25),range=30)
    blue_general1 = SquadLeader(118, 128, name="BlueGeneral1", squad="B1", team="blue", color=(25, 0, 155),range=30)
    
    
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
    
    agents.clear()
    name_to_troop.clear()
    
    # Pre-render the map surface
    cached_map_surface = create_map_surface()
    
    # Assign modes to troops by index (defaults to 'normal')
    mode_assignments = {
        i: "normal" for i in range(20)
    }
    
    # Real SPADE initialization
    for idx, t in enumerate(troops):
        mode = mode_assignments.get(idx, "normal")
        # Provide a simple JID based on troop name.
        jid = f"{t.name.replace(' ', '').lower()}@localhost"
        password = "password"
        
        if isinstance(t, SquadLeader):
            agent = SquadLeaderAgent(jid, password, t, troops, mode)
        else:
            agent = TroopAgent(jid, password, t, troops, mode)
            
        t.agent = agent
        agents.append(agent)
        name_to_troop[t.name] = t
    
    async def start_spade_agents():
        print("Starting all SPADE agents...")
        for agent in agents:
            try:
                await agent.start(auto_register=True)
            except Exception as e:
                print(f"Failed to start agent {agent.jid}: {e}")
    
    # Start agents
    await start_spade_agents()
    
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
                if event.key == pygame.K_w:  # Issue wait order for red leader
                    red_leader.broadcast_and_command("wait_for_signal", {"delay": 5}, troops)
                    print("Manual Command: RedLeader orders WAIT")
        
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
            pass
        
        # Yield to asyncio event loop so SPADE can process messages
        await asyncio.sleep(0.01)
            
        
        # Draw
        game_time += 1
        screen.fill([0, 127+int(127*sin(game_time/3600)), 40+int(-40*sin(game_time/3600-180))])  # Fill the screen with background color
        
        # Draw the cached map
        draw_map(screen, cached_map_surface, game_cam_x, game_cam_y, game_cam_zoom)
        
        # Draw troops
        for t in troops:
            t.draw(screen, game_cam_x, game_cam_y, game_cam_zoom)
        
        pygame.display.flip()
        clock.tick(60)
     
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    spade.run(main(), embedded_xmpp_server=True)
 
