from bravo.ibravo import IRecipe
from bravo.plugin import retrieve_plugins
from bravo.packets.beta import make_packet
from bravo.inventory import Slot, SerializableSlots

class comblist(object):
    def __init__(self, a, b):
        self.l = a, b
        self.offset = len(a)
        self.length = sum(map(len,self.l))

    def __len__(self):
        return self.length

    def __getitem__(self, key):
        if key < self.offset:
            return self.l[0][key]
        key -= self.offset
        if key < self.length:
            return self.l[1][key]
        raise IndexError

    def __setitem__(self, key, value):
        if key < 0:
            raise IndexError
        if key < self.offset:
            self.l[0][key] = value
            return
        key -= self.offset
        if key < self.length:
            self.l[1][key] = value
            return
        raise IndexError

def pad_to_stride(recipe, rstride, cstride):
    """
    Pad a recipe out to a given stride.

    :param tuple recipe: a recipe
    :param int rstride: stride of the recipe
    :param int cstride: stride of the crafting table
    """

    def grouper(n, iterable):
        args = [iter(iterable)] * n
        for i in zip(*args):
            yield i

    if rstride > cstride:
        raise ValueError("Recipe is wider than crafting!")

    pad = (None,) * (cstride - rstride)
    g = grouper(rstride, recipe)
    padded = list(next(g))
    for row in g:
        padded.extend(pad)
        padded.extend(row)

    return padded

class SlotsSet(SerializableSlots):
    '''
    Base calss for different slot configurations except player's inventory
    '''

    crafting = 0          # crafting slots (inventory, workbench, furnace)
    fuel = 0              # furnace
    storage = 0           # chest
    crafting_stride = 0

    def __init__(self):

        if self.crafting:
            self.crafting = [None] * self.crafting
            self.crafted = [None]
        else:
            self.crafting = self.crafted = []

        if self.fuel:
            self.fuel = [None]
        else:
            self.fuel = []

        if self.storage:
            self.storage = [None] * self.storage
        else:
            self.storage = []
        self.dummy = [None] * 36 # represents gap in serialized structure:
                                 # storage (27) + holdables(9) from player's
                                 # inventory (notchian)

    @property
    def metalist(self):
        return [self.crafted, self.crafting, self.fuel, self.storage, self.dummy]

    def update_crafted(self):
        # override me
        pass

    def close(self, wid):
        # override me, see description in Crafting
        return [], ""

class Crafting(SlotsSet):
    '''
    Base crafting class. Never shall be instantinated directly.
    '''

    crafting = 4
    crafting_stride = 2

    def __init__(self):
        SlotsSet.__init__(self)
        self.recipe = None
        self.recipe_offset = None

    def update_crafted(self):
        self.check_recipes()
        if self.recipe is None:
            self.crafted[0] = None
        else:
            provides = self.recipe.provides
            self.crafted[0] = Slot(provides[0][0], provides[0][1], provides[1])

    def select_crafted(self, index, alternate, shift, selected = None):
        """
        Handle a slot selection on a crafted output.

        Returns: ( True/False, new selection )
        """

        if self.recipe and self.crafted[0]:
            if selected is None:
                selected = self.crafted[0]
                self.crafted[0] = None
            else:
                sslot = selected
                if sslot.holds(self.recipe.provides[0]):
                    selected = sslot.increment(self.recipe.provides[1])
                else:
                    # Mismatch; don't allow it.
                    return (False, selected)

            self.reduce_recipe()
            self.check_recipes()
            if self.recipe is None:
                self.crafted[0] = None
            else:
                provides = self.recipe.provides
                self.crafted[0] = Slot(provides[0][0], provides[0][1],
                    provides[1])

            return (True, selected)
        else:
            # Forbid placing things in the crafted slot.
            return (False, selected)

    def check_recipes(self):
        """
        See if the crafting table matches any recipes.

        :returns: the recipe and offset, or None if no matches could be made
        """

        # This isn't perfect, unfortunately, but correctness trumps algorithmic
        # perfection. (For now.)
        for name, recipe in sorted(retrieve_plugins(IRecipe).iteritems()):
            dims = recipe.dimensions

            # Skip recipes that don't fit our crafting table.
            if (dims[0] > self.crafting_stride or
                dims[1] > len(self.crafting) // self.crafting_stride):
                continue

            padded = pad_to_stride(recipe.recipe, dims[0],
                self.crafting_stride)

            for offset in range(len(self.crafting) - len(padded) + 1):
                nones = self.crafting[:offset]
                nones += self.crafting[len(padded) + offset:]
                if not all(i is None for i in nones):
                    continue

                matches_needed = len(padded)

                for i, j in zip(padded,
                    self.crafting[offset:len(padded) + offset]):
                    if i is None and j is None:
                        matches_needed -= 1
                    elif i is not None and j is not None:
                        skey, scount = i
                        if j.holds(skey) and j.quantity >= scount:
                            matches_needed -= 1

                    if matches_needed == 0:
                        # Jackpot!
                        self.recipe = recipe
                        self.recipe_offset = offset
                        return

        self.recipe = None

    def reduce_recipe(self):
        """
        Reduce a crafting table according to a recipe.

        This function returns None; the crafting table is modified in-place.

        This function assumes that the recipe already fits the crafting table
        and will not do additional checks to verify this assumption.
        """

        offset = self.recipe_offset

        padded = pad_to_stride(self.recipe.recipe, self.recipe.dimensions[0],
            self.crafting_stride)

        for index, slot in enumerate(padded):
            if slot is not None:
                index += offset
                rcount = slot[1]
                slot = self.crafting[index]
                self.crafting[index] = slot.decrement(rcount)

    def close(self, wid):
        '''
        Clear crafting areas and return items to drop and packets to send to client
        '''
        items = []
        packets = ""

        # process crafting area
        for i, itm in enumerate(self.crafting):
            if itm is not None:
                items.append(itm)
                self.crafting[i] = None
                packets += make_packet("window-slot", wid=wid,
                                        slot=i+1, primary=-1)
        self.crafted[0] = None

        return items, packets

class Workbench(Crafting):

    crafting = 9
    crafting_stride = 3
    title = "Workbench"
    identifier = "workbench"
    slots_num = 9

class ChestStorage(SlotsSet):

    storage = 27
    identifier = "chest"
    title = "Chest"
    slots_num = 27

    def __init__(self):
        SlotsSet.__init__(self)
        self.title = "Chest"

class LargeChestStorage(SlotsSet):
    """
    LargeChest is a wrapper around 2 ChestStorages
    """

    identifier = "chest"
    title = "LargeChest"
    slots_num = 54

    def __init__(self, chest1, chest2):
        SlotsSet.__init__(self)
        # NOTE: chest1 and chest2 are ChestStorage.storages
        self.storage = comblist(chest1, chest2)

    @property
    def metalist(self):
        return [self.storage]

class FurnaceStorage(SlotsSet):

    #TODO: Make sure notchian furnace have following slots order:
    #      2 -crafted, 0 - crafting, 1 - fuel
    #      Override SlotsSet.metalist() property if not.

    crafting = 1
    fuel = 1
    title = "Furnace"
    identifier = "furnace"
    slots_num = 3

    def select_crafted(self, index, alternate, shift, selected = None):
        """
        Handle a slot selection on a crafted output.
        Returns: ( True/False, new selection )
        """

        if self.crafted[0]:
            if selected is None:
                selected = self.crafted[0]
                self.crafted[0] = None
            else:
                sslot = selected
                if sslot.holds(self.crafted[0]):
                    selected = sslot.increment(self.crafted[0].quantity)
                    self.crafted[0] = None
                else:
                    # Mismatch; don't allow it.
                    return (False, selected)

            return (True, selected)
        else:
            # Forbid placing things in the crafted slot.
            return (False, selected)

    #@property
    #def metalist(self):
    #    return [self.crafting, self.fuel, self.crafted]
