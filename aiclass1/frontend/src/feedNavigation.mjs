// Deterministic, one-step navigation; never derive the active video from browser scroll positions.
export function swipeDirection(dx,dy,threshold=60){
 if(!Number.isFinite(dx)||!Number.isFinite(dy))return 0;
 if(Math.abs(dy)<threshold || Math.abs(dy)<Math.abs(dx)*1.2)return 0;
 return dy<0?1:-1;
}
export function stepVideo(current,delta,total=13){
 if(!Number.isInteger(current)||!Number.isInteger(total)||total<1)return current;
 if(!Number.isFinite(delta)||delta===0)return current;
 return ((current-1+(delta>0?1:-1)+total)%total)+1;
}
