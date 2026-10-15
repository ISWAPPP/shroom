// Single place for UI icons: Material Symbols Outlined (Apache-2.0), self-hosted (CSP allows only 'self').
import React from 'react';
import './symbols.css'; // subset: scripts/subset-icons.sh

export type IconT = {glyph: string};
const sym = (glyph: string): IconT => ({glyph});
export const Diamond = sym('diamond'),
  Paperclip = sym('attach_file'),
  Image = sym('image'),
  MessageCircle = sym('chat'),
  SettingsIcon = sym('settings'),
  LogOut = sym('logout'),
  FileText = sym('description'),
  SquareSlash = sym('terminal'),
  Square = sym('stop'),
  ArrowUp = sym('arrow_upward'),
  KeyRound = sym('key'),
  UserIcon = sym('person'),
  Users = sym('group'),
  Scale = sym('balance'),
  X = sym('close'),
  Star = sym('star'),
  RotateCw = sym('restart_alt'),
  Play = sym('play_arrow'),
  TriangleAlert = sym('warning'),
  Ban = sym('block'),
  Check = sym('check'),
  Plus = sym('add'),
  Terminal = sym('terminal'),
  ScrollText = sym('receipt_long'),
  Trash2 = sym('delete'),
  Gauge = sym('speed'),
  Activity = sym('monitoring'),
  BookOpen = sym('menu_book'),
  Library = sym('local_library'),
  Box = sym('deployed_code'),
  ChevronDown = sym('expand_more'),
  Download = sym('download'),
  Folder = sym('forum'),
  OpenInNew = sym('open_in_new'),
  Inventory = sym('inventory_2'),
  MoreVert = sym('more_vert'),
  Edit = sym('edit'),
  MenuIcon = sym('menu'),
  SearchIcon = sym('search'),
  Lightbulb = sym('lightbulb'),
  Palette = sym('palette'),
  LightMode = sym('light_mode'),
  DarkMode = sym('dark_mode'),
  Contrast = sym('contrast'),
  AutoAwesome = sym('auto_awesome'),
  Schedule = sym('schedule'),
  Pause = sym('pause'),
  History = sym('history'),
  Send = sym('send'),
  PlaylistAdd = sym('playlist_add'),
  AltRoute = sym('alt_route'),
  CallSplit = sym('call_split'),
  ContactSupport = sym('contact_support'),
  MoreHoriz = sym('more_horiz'),
  FrontHand = sym('front_hand'),
  ContentCopy = sym('content_copy'),
  Notifications = sym('notifications'),
  PushPin = sym('push_pin'),
  Share = sym('share'),
  Refresh = sym('refresh'),
  HelpIcon = sym('help'),
  CheckCircle = sym('check_circle'),
  ErrorIcon = sym('error'),
  StopCircle = sym('stop_circle');

export function Ic({i, size = 20, className = '', fill = false}: {i: IconT; size?: number; className?: string; fill?: boolean}) {
  return (
    <span
      className={'ic material-symbols-outlined ' + className}
      aria-hidden="true"
      style={{
        fontSize: size,
        fontVariationSettings: `'FILL' ${fill ? 1 : 0}, 'wght' 400, 'GRAD' 0, 'opsz' ${Math.min(48, Math.max(20, size))}`,
      }}
    >
      {i.glyph}
    </span>
  );
}
