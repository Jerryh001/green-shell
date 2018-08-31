import json
import os
possible_ID=[
    "358105527ed224bcc7c0bde052c63b9c80443259",
    "0a67ad27dbafe3a51dd80c5681dcec953ec21a40",
    "bce1ca3850577138b540d847f4d470526d263379",
    "55c0ce8c08125e1e1a24bcde9e8b1f5786623acf"
    ]

possible_name=["微光閃耀"]

possible_message=["HanG","BFD","Jerryh001"]
possible_exact_message=["是"]

possible_keyword=["@","GS","Glimmer Sparkle","GlimmerSparkle","Glimmer-Sparkle","小馬","pony","MLP"]

trusted_user={
    "Jerryh001":["3b0f2a3a8a2a35a9c9727f188772ba095b239668"],
    "tugumi":["e905f62a1b3eebf043ec13e63d2cece2def767e5"],
    "DIO":["6095df2de39fc5a658c3e148abb627d5da17d257"],
    "Buttman":["70794a3ecc5da7683cab9795d41db7979bdebd11","95e0b3d0da20e794e9a85f5141bae1f2a7166198"],#-人◕-◡◡-◕人-
    "HanG":["5df087e5e341f555b0401fb69f89b5937ae7e313"],
    "BFD":["35bd559ba2f02e4f90f51f80ac725a0eaebf6e34"],
    "最討厭的傑":["8a7c97f43f75df47bc25e18f32746032847caf4b"],
    "AJL":["dd0e447ef86c95a33f2ce65f6960f0ac16694cfe"],
    "TJacky":["e2d8fc6b6d72af4a59478b2b2baac8730357f5cd"],
    "G4-pony-love":["8d987a6b3fd94c826b3071aab8c56dd9363813d2"],
    "G5-pony-love":["37ac092b1563d396e17b9adf764b2b057a1f6b96"],
    "老伯":["a21ee7e07b46cdb0716f1f46603fc78fd9776027"],
    "ㄐㄖ":["d3db9977ed561d1e27a07f42a3ee94b17fec55d6"]
    }

all_list={
    "ID":possible_ID,
    "name":possible_name,
    "message":possible_message,
    "EXmessage":possible_exact_message,
    "keyword":possible_keyword
}

def D(jlist,output):

    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, output+".json")
    json.dump(jlist,open(filename, 'w',encoding='utf8'),ensure_ascii=False)

if __name__=="__main__":
    D(all_list,"keyword")
    D(trusted_user,"trusted_user")