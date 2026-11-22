export type MediaPreloader={
 enter(id:number):string;
 prepare(id:number):Promise<number[]>;
 stop():void;
 dispose():void;
 getPreparedIds():number[];
};
export function createMediaPreloader(options:{
 urlFor:(id:number)=>string;
 maxId?:number;
 fetcher?:(url:string,options:RequestInit)=>Promise<Response>;
 createObjectURL?:(blob:Blob)=>string;
 revokeObjectURL?:(url:string)=>void;
}):MediaPreloader;
