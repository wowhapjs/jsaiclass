export type MediaPreloader={
 enter(id:number):string;
 prepare(id:number):Promise<number[]>;
 stop():void;
 forget(id:number):void;
 clear():void;
 dispose():void;
 getPreparedIds():number[];
};
export function createMediaPreloader(options:{
 urlFor:(id:number)=>string;
 maxId?:number;
 fetcher?:(url:string,options:RequestInit)=>Promise<Response>;
 createObjectURL?:(blob:Blob)=>string;
 revokeObjectURL?:(url:string)=>void;
 onPrepared?:(id:number,blobUrl:string)=>void;
}):MediaPreloader;
