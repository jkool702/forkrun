# splits a base 64 sequence into every possible 4-bit and 8-bit sequence

echo "${b64[x86_64_v4]}" | sed -E 's/^((....)*).*$/\1/; s/^(.)(.)(.)(.*)$/\1\2\3\4 \2\3\4  \3\4   \4   /; s/(....)/\1\n/g' | sed -zE 's/^(....)\n/\1\n\1\n/; s/\n(....)\n(....)\n(....)/\1\n\1\n\1\2\n\2\n\2\3\n\3\n\3/g'
